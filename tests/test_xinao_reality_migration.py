from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import services.xinao_perpetual_world_compute.reality_migration as reality_migration_module
from services.xinao_perpetual_world_compute.reality_migration import (
    ActiveChildProcessError,
    DestinationConflictError,
    RealityMigrationError,
    SourceTreeChangedError,
    inventory_live_reality,
    migrate_live_reality_copy_first,
    observe_mixed_live_retirement_consumers,
    readback_live_reality_migration,
    restore_retired_mixed_live_reality,
    retire_mixed_live_reality,
    transform_research_source,
    validate_retirement_runtime_bindings,
)


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run_legacy_import(
    *,
    overlay_code: Path,
    base_code: Path,
    repo: Path,
    live: Path,
    import_helper: bool = True,
) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(overlay_code), str(base_code)))
    environment["XINAO_WORLD_WORKSPACE"] = str(repo)
    environment["XINAO_LIVE_REALITY_ROOT"] = str(live)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json\n"
                "import xinao_legacy_research.analysis as analysis\n"
                + (
                    "import xinao_legacy_research.helper as helper\n"
                    "print(json.dumps({'analysis': analysis.__file__, 'helper': helper.__file__}))\n"
                    if import_helper
                    else "print(json.dumps({'analysis': analysis.__file__}))\n"
                )
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(completed.stdout)


def _run_nested_legacy_import(
    *, overlay_code: Path, base_code: Path, repo: Path, live: Path
) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(overlay_code), str(base_code)))
    environment["XINAO_WORLD_WORKSPACE"] = str(repo)
    environment["XINAO_LIVE_REALITY_ROOT"] = str(live)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json\n"
                "import xinao_legacy_research.pkg.mod as mod\n"
                "print(json.dumps({'value': mod.VALUE, 'path': mod.__file__}))\n"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(completed.stdout)


def _make_repo(root: Path) -> Path:
    live = root / "xinao" / "reality" / "live"
    source = b"""from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from xinao.reality.live.helper import draw

HOLDOUT_STORE = (
    ROOT / "xinao" / "reality" / "live" / "pre203_holdout_fixture"
)
"""
    helper = b"""from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[3]

def draw() -> float:
    return random.Random(17).random()
"""
    _write(live / "analysis.py", source)
    _write(live / "helper.py", helper)
    _write(live / "__pycache__" / "analysis.cpython-313.pyc", b"bytecode")
    _write(live / "pre203_holdout_fixture" / ".draw-ingest.lock", b"0")
    _write(live / "pre203_overlap_attestation" / ".draw-ingest.lock", b"0")
    _write(live / "pre203_holdout_fixture" / "raw" / "draws" / "aa" / "aa.bin", b"raw")
    _write(
        live / "pre203_holdout_fixture" / "captures" / "capture-1" / "capture.json",
        b'{"schema":"capture"}\n',
    )
    _write(
        live / "pre203_holdout_fixture" / "events" / "1" / "event.json",
        b'{"schema":"event"}\n',
    )
    _write(
        live / "pre203_holdout_fixture" / "manifests" / "v1.json",
        b'{"schema":"manifest"}\n',
    )
    _write(
        live / "pre203_holdout_fixture" / "CURRENT.json",
        b'{"manifest_path":"manifests/v1.json"}\n',
    )
    _write(live / "publisher_legal_identity_audit.json", b'{"result":"derived"}\n')
    _write(live / "retro_masked_virtual_shadows" / "shadow.json", b'{"virtual":true}\n')
    return root


def _make_workspace(root: Path, canonical: Path) -> Path:
    live = root / "xinao" / "reality" / "live"
    canonical_live = canonical / "xinao" / "reality" / "live"
    changed = (
        (canonical_live / "analysis.py")
        .read_bytes()
        .replace(b"helper import draw", b"helper import draw as draw")
    )
    _write(live / "analysis.py", changed)
    _write(
        live / "extra.py",
        b"""from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
VALUE = "workspace-extra"
""",
    )
    _write(
        live / "pre203_holdout_fixture" / "raw" / "draws" / "aa" / "aa.bin",
        (
            canonical_live / "pre203_holdout_fixture" / "raw" / "draws" / "aa" / "aa.bin"
        ).read_bytes(),
    )
    _write(live / "workspace_result.json", b'{"workspace":"one"}\n')
    _write(
        live / "pre203_holdout_fixture" / "raw" / "draws" / "bb" / "bb.bin",
        b"workspace-raw",
    )
    _write(
        live / "pre203_holdout_fixture" / "captures" / "workspace" / "capture.json",
        b'{"schema":"workspace-capture"}\n',
    )
    _write(live / "__pycache__" / "extra.cpython-313.pyc", b"workspace-bytecode")
    _write(live / "workspace.lock", b"0")
    return root


def test_inventory_is_stable_exhaustive_and_classifies_named_exclusions(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")

    first = inventory_live_reality(repo)
    second = inventory_live_reality(repo)

    assert first["source_tree_sha256"] == second["source_tree_sha256"]
    assert first["payload_tree_sha256"] == second["payload_tree_sha256"]
    assert first["counts"] == {
        "derived_research": 2,
        "durable_metadata": 4,
        "excluded_bytecode": 1,
        "excluded_lock": 2,
        "raw_live_reality": 1,
        "research_source": 1,
        "simulation_source": 1,
    }
    assert len(first["entries"]) == 12
    entries = {entry["relative_path"]: entry for entry in first["entries"]}
    assert entries["analysis.py"]["source_sha256"] != entries["analysis.py"]["payload_sha256"]
    assert entries["__pycache__/analysis.cpython-313.pyc"]["payload_sha256"] is None
    assert entries["pre203_overlap_attestation/.draw-ingest.lock"]["classification"] == (
        "excluded_lock"
    )


def test_copy_first_migration_builds_live_base_and_workspace_delta(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = _make_workspace(tmp_path / "world-01", repo)
    empty_workspace = tmp_path / "world-02"
    empty_workspace.mkdir()
    live_target = tmp_path / "runtime" / "xinao" / "live-reality"
    compute_target = tmp_path / "runtime" / "world-compute"
    source_before = _snapshot(repo)
    workspace_live = workspace / "xinao" / "reality" / "live"
    workspace_before = _snapshot(workspace_live)

    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
        workspace_roots={"world-01": workspace, "world-02": empty_workspace},
        active_child_pids={},
    )

    assert result["status"] == "verified"
    assert result["readback"]["status"] == "verified"
    assert result["source_preserved"] is True
    assert _snapshot(repo) == source_before
    assert _snapshot(workspace_live) == workspace_before

    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_view = result["lineage_effective_views"]["world-01"]
    assert first_view["lineage_id"] == "world-01"
    assert first_view["workspace_key"] == "world-01"
    assert Path(first_view["private_effective_live_root"]) == (
        workspace.resolve() / ".xinao-world-runtime" / "live-reality"
    )
    assert not Path(first_view["private_effective_live_root"]).is_relative_to(
        workspace.resolve() / "xinao" / "reality" / "live"
    )
    assert Path(first_view["private_live_materialization"]["receipt_path"]).is_relative_to(
        compute_target.resolve()
    )
    assert not Path(first_view["private_live_materialization"]["receipt_path"]).is_relative_to(
        workspace.resolve()
    )
    binding_inputs = first_view["runtime_binding_inputs"]
    assert binding_inputs == manifest["workspace_overlays"][0]["runtime_binding_inputs"]
    view_manifest = json.loads(
        Path(first_view["effective_view_manifest_path"]).read_text(encoding="utf-8")
    )
    assert binding_inputs == view_manifest["runtime_binding_inputs"]
    assert binding_inputs == {
        "schema": "xinao.runtime-binding-migration-inputs.v1",
        "lineage_id": "world-01",
        "workspace": str(workspace.resolve()),
        "base_manifest_path": manifest["base_bundle"]["manifest_path"],
        "base_manifest_sha256": manifest["base_bundle"]["manifest_sha256"],
        "effective_code_root": first_view["effective_code_root"],
        "effective_python_path": first_view["effective_python_path"],
        "effective_code_manifest_path": first_view["effective_code_manifest_path"],
        "effective_code_manifest_sha256": first_view["effective_code_manifest_sha256"],
        "effective_code_tree_sha256": first_view["effective_code_payload_tree_sha256"],
        "private_live_root": first_view["private_effective_live_root"],
        "live_seed_receipt_path": first_view["private_live_materialization"]["receipt_path"],
        "live_seed_receipt_sha256": first_view["private_live_materialization"]["receipt_sha256"],
    }
    canonical_live_root = Path(manifest["canonical_live_bundle"]["root"])
    assert (
        canonical_live_root / "pre203_holdout_fixture" / "raw" / "draws" / "aa" / "aa.bin"
    ).read_bytes() == b"raw"
    assert (canonical_live_root / "pre203_holdout_fixture" / "CURRENT.json").exists()
    assert not (canonical_live_root / "analysis.py").exists()
    assert not (canonical_live_root / "publisher_legal_identity_audit.json").exists()
    assert not list(canonical_live_root.rglob("*.lock"))
    assert not list(canonical_live_root.rglob("*.pyc"))
    base_root = Path(manifest["base_bundle"]["root"])
    migrated_source = (base_root / "code" / "xinao_legacy_research" / "analysis.py").read_text(
        encoding="utf-8"
    )
    assert "from xinao_legacy_research.helper import draw" in migrated_source
    assert "XINAO_WORLD_WORKSPACE" in migrated_source
    assert "XINAO_LIVE_REALITY_ROOT" in migrated_source
    assert "xinao.reality.live" not in migrated_source
    assert "parents[3]" not in migrated_source
    assert (base_root / "code" / "xinao_legacy_research" / "__init__.py").exists()
    assert (base_root / "derived" / "publisher_legal_identity_audit.json").exists()
    assert not list(base_root.rglob("*.pyc"))
    assert not list(base_root.rglob("*.lock"))

    overlays = {item["workspace_key"]: item for item in manifest["workspace_overlays"]}
    first_overlay = Path(overlays["world-01"]["overlay_root"])
    assert (first_overlay / "code" / "xinao_legacy_research" / "analysis.py").exists()
    assert (first_overlay / "code" / "xinao_legacy_research" / "extra.py").exists()
    assert (first_overlay / "files" / "workspace_result.json").exists()
    assert not (first_overlay / "files" / "pre203_holdout_fixture" / "raw").exists()
    assert overlays["world-01"]["unchanged_base_entry_count"] == 1
    live_delta_root = Path(overlays["world-01"]["live_reality_delta_root"])
    assert (
        live_delta_root / "pre203_holdout_fixture" / "raw" / "draws" / "bb" / "bb.bin"
    ).read_bytes() == b"workspace-raw"
    assert (
        live_delta_root / "pre203_holdout_fixture" / "captures" / "workspace" / "capture.json"
    ).exists()
    assert overlays["world-01"]["live_reality_delta_entry_count"] == 2
    assert overlays["world-02"]["delta_entry_count"] == 0

    effective_python_path = Path(overlays["world-01"]["effective_python_path"])
    assert not (effective_python_path / "xinao_legacy_research" / "helper.py").exists()
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import xinao_legacy_research.extra as extra; print(extra.__file__)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(effective_python_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "XINAO_WORLD_WORKSPACE": str(workspace),
            "XINAO_LIVE_REALITY_ROOT": overlays["world-01"]["private_effective_live_root"],
        },
    )
    assert (
        Path(completed.stdout.strip()).resolve()
        == (effective_python_path / "xinao_legacy_research" / "extra.py").resolve()
    )

    assert manifest["canonical_inventory"]["source_tree_sha256"]
    assert manifest["canonical_inventory"]["payload_tree_sha256"]
    assert manifest["base_bundle"]["payload_tree_sha256"] == result["base_payload_tree_sha256"]
    for copy in manifest["copies"]:
        if copy["source_path"] is not None:
            assert copy["source_sha256"]
        assert copy["payload_sha256"]

    repeated = migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
        workspace_roots={"world-02": empty_workspace, "world-01": workspace},
        active_child_pids=[],
        expected_source_tree_sha256=manifest["canonical_inventory"]["source_tree_sha256"],
    )
    assert repeated["manifest_sha256"] == result["manifest_sha256"]
    assert repeated["migration_id"] == result["migration_id"]
    assert repeated["manifest_disposition"] == "verified_existing"


def test_any_reported_active_child_pid_fails_before_destination_creation(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    live_target = tmp_path / "runtime" / "live-reality"
    compute_target = tmp_path / "runtime" / "world-compute"

    with pytest.raises(ActiveChildProcessError, match="ACTIVE_CHILD_PIDS"):
        migrate_live_reality_copy_first(
            repo,
            live_reality_root=live_target,
            world_compute_root=compute_target,
            active_child_pids={"run.world-01": 999_999_999},
        )

    assert not live_target.exists()
    assert not compute_target.exists()


def test_excluded_cache_drift_gets_new_source_identity_without_rewriting_base(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    live_target = tmp_path / "runtime" / "live-reality"
    compute_target = tmp_path / "runtime" / "world-compute"
    first = migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
    )
    pyc = repo / "xinao" / "reality" / "live" / "__pycache__" / "analysis.cpython-313.pyc"
    pyc.write_bytes(b"regenerated-bytecode")

    second = migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
    )

    assert second["migration_id"] != first["migration_id"]
    assert second["manifest_sha256"] != first["manifest_sha256"]
    assert second["base_bundle_root"] == first["base_bundle_root"]
    assert second["base_payload_tree_sha256"] == first["base_payload_tree_sha256"]
    assert second["status"] == "verified"


def test_readback_and_replay_reject_tampered_payload_without_touching_source(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    live_target = tmp_path / "runtime" / "live-reality"
    compute_target = tmp_path / "runtime" / "world-compute"
    source_before = _snapshot(repo)
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    raw_copy = next(
        copy
        for copy in manifest["copies"]
        if copy["surface"] == "canonical_live_reality_provenance"
    )
    Path(raw_copy["destination_path"]).write_bytes(b"tampered")

    with pytest.raises(RealityMigrationError, match="readback failed"):
        readback_live_reality_migration(
            Path(result["manifest_path"]),
            expected_manifest_sha256=result["manifest_sha256"],
        )
    with pytest.raises(DestinationConflictError, match="conflict"):
        migrate_live_reality_copy_first(
            repo,
            live_reality_root=live_target,
            world_compute_root=compute_target,
        )
    assert _snapshot(repo) == source_before


def test_rejects_unsafe_workspace_key_and_overlapping_destination(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(RealityMigrationError, match="unsafe workspace key"):
        migrate_live_reality_copy_first(
            repo,
            live_reality_root=tmp_path / "runtime" / "live",
            world_compute_root=tmp_path / "runtime" / "compute",
            workspace_roots={"../escape": workspace},
        )
    with pytest.raises(RealityMigrationError, match="must equal its exact lineage_id"):
        migrate_live_reality_copy_first(
            repo,
            live_reality_root=tmp_path / "runtime" / "live",
            world_compute_root=tmp_path / "runtime" / "compute",
            workspace_roots={"world-01": workspace},
        )
    with pytest.raises(RealityMigrationError, match="overlap"):
        migrate_live_reality_copy_first(
            repo,
            live_reality_root=repo / "runtime" / "live",
            world_compute_root=tmp_path / "runtime" / "compute",
        )


@pytest.mark.parametrize(
    "implicit_root",
    [
        "Path( __file__ ).resolve().parents[3]",
        "Path(__file__).resolve().parents [3]",
    ],
)
def test_semantic_repo_root_rewrite_cannot_be_bypassed_by_whitespace(
    implicit_root: str,
) -> None:
    payload = transform_research_source(
        f"from pathlib import Path\nROOT = {implicit_root}\n".encode()
    ).decode()

    assert "XINAO_WORLD_WORKSPACE" in payload
    assert "parents" not in payload


def test_from_namespace_live_import_is_rewritten_with_alias() -> None:
    payload = transform_research_source(
        b"from xinao.reality import live as old_live\nVALUE = old_live\n"
    ).decode()

    assert "import xinao_legacy_research as old_live" in payload
    assert "xinao.reality" not in payload

    unaliased = transform_research_source(b"from xinao.reality import live\n").decode()
    assert "import xinao_legacy_research as live" in unaliased


def test_dynamic_namespace_alias_access_fails_closed() -> None:
    with pytest.raises(RealityMigrationError, match="dynamic alias access"):
        transform_research_source(b"import xinao.reality as reality\nVALUE = reality.live\n")
    with pytest.raises(RealityMigrationError, match="unaliased import"):
        transform_research_source(b"import xinao.reality\nVALUE = xinao.reality.live.helper\n")
    with pytest.raises(RealityMigrationError, match="dynamic alias access"):
        transform_research_source(b"from xinao import reality\nVALUE = reality.live.helper\n")


def test_source_package_init_is_extended_without_collision_and_overlay_imports(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    _write(
        repo / "xinao" / "reality" / "live" / "__init__.py",
        b'PACKAGE_ORIGIN = "canonical"\n',
    )
    workspace = _make_workspace(tmp_path / "world-01", repo)
    _write(
        workspace / "xinao" / "reality" / "live" / "__init__.py",
        b'PACKAGE_ORIGIN = "workspace"\n',
    )
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    base_root = Path(manifest["base_bundle"]["root"])
    overlay_root = Path(manifest["workspace_overlays"][0]["overlay_root"])
    migrated_init = (base_root / "code" / "xinao_legacy_research" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert 'PACKAGE_ORIGIN = "canonical"' in migrated_init
    assert "XINAO_LEGACY_RESEARCH_NAMESPACE_V1" in migrated_init
    overlay_init = (overlay_root / "code" / "xinao_legacy_research" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert 'PACKAGE_ORIGIN = "workspace"' in overlay_init
    assert "XINAO_LEGACY_RESEARCH_NAMESPACE_V1" in overlay_init
    imported = _run_legacy_import(
        overlay_code=overlay_root / "code",
        base_code=base_root / "code",
        repo=repo,
        live=tmp_path / "runtime" / "live",
    )
    assert (
        Path(imported["analysis"]).resolve()
        == (overlay_root / "code" / "xinao_legacy_research" / "analysis.py").resolve()
    )
    assert (
        Path(imported["helper"]).resolve()
        == (base_root / "code" / "xinao_legacy_research" / "helper.py").resolve()
    )


def test_nested_package_init_extends_overlay_and_base_portions(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    canonical_live = repo / "xinao" / "reality" / "live"
    _write(canonical_live / "pkg" / "__init__.py", b'PACKAGE = "base"\n')
    _write(canonical_live / "pkg" / "mod.py", b'VALUE = "base"\n')
    workspace = _make_workspace(tmp_path / "world-01", repo)
    workspace_live = workspace / "xinao" / "reality" / "live"
    _write(workspace_live / "pkg" / "__init__.py", b'PACKAGE = "base"\n')
    _write(workspace_live / "pkg" / "mod.py", b'VALUE = "overlay"\n')
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    base_root = Path(manifest["base_bundle"]["root"])
    overlay_root = Path(manifest["workspace_overlays"][0]["overlay_root"])

    imported = _run_nested_legacy_import(
        overlay_code=overlay_root / "code",
        base_code=base_root / "code",
        repo=repo,
        live=tmp_path / "runtime" / "live",
    )
    assert imported["value"] == "overlay"
    assert (
        Path(imported["path"]).resolve()
        == (overlay_root / "code" / "xinao_legacy_research" / "pkg" / "mod.py").resolve()
    )


def test_readback_detects_absent_workspace_live_becoming_empty_directory(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = tmp_path / "world-01"
    workspace.mkdir()
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )
    (workspace / "xinao" / "reality" / "live").mkdir(parents=True)

    with pytest.raises(SourceTreeChangedError, match="workspace source tree changed"):
        readback_live_reality_migration(
            Path(result["manifest_path"]),
            expected_manifest_sha256=result["manifest_sha256"],
        )


def _make_complete_clone(root: Path, canonical: Path) -> Path:
    canonical_live = canonical / "xinao" / "reality" / "live"
    clone_live = root / "xinao" / "reality" / "live"
    for source in canonical_live.rglob("*"):
        if source.is_file():
            _write(clone_live / source.relative_to(canonical_live), source.read_bytes())
    return root


def _import_probe(
    python_path: Path, module: str, environment: dict[str, str]
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", f"import {module} as target; print(target.VALUE)"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(python_path), **environment},
    )


def test_complete_clone_effective_view_preserves_override_deletion_and_base_only(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    canonical_live = repo / "xinao" / "reality" / "live"
    _write(canonical_live / "base_only.py", b'VALUE = "base-only"\n')
    _write(canonical_live / "override.py", b'VALUE = "base"\n')
    _write(canonical_live / "deleted.py", b'VALUE = "must-not-return"\n')
    workspace = _make_complete_clone(tmp_path / "world-01", repo)
    workspace_live = workspace / "xinao" / "reality" / "live"
    _write(workspace_live / "override.py", b'VALUE = "overlay"\n')
    (workspace_live / "deleted.py").unlink()
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )
    view = result["lineage_effective_views"]["world-01"]
    python_path = Path(view["effective_python_path"])
    environment = view["runtime_environment"]

    assert _import_probe(
        python_path, "xinao_legacy_research.base_only", environment
    ).stdout.strip() == ("base-only")
    assert _import_probe(
        python_path, "xinao_legacy_research.override", environment
    ).stdout.strip() == ("overlay")
    deleted = _import_probe(python_path, "xinao_legacy_research.deleted", environment)
    assert deleted.returncode != 0
    assert "ModuleNotFoundError" in deleted.stderr

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    overlay = manifest["workspace_overlays"][0]
    deletion_paths = {item["relative_path"] for item in overlay["deletions"]}
    assert "deleted.py" in deletion_paths
    assert overlay["python_path_order"] == [str(python_path)]
    assert overlay["runtime_environment"]["XINAO_WORLD_WORKSPACE"] == str(workspace.resolve())


def test_deleted_source_init_is_not_recreated_in_effective_runtime_view(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    canonical_live = repo / "xinao" / "reality" / "live"
    _write(canonical_live / "__init__.py", b'CANONICAL_SIDE_EFFECT = "deleted"\n')
    _write(canonical_live / "standalone.py", b'VALUE = "still-present"\n')
    workspace = _make_complete_clone(tmp_path / "root-main", repo)
    (workspace / "xinao" / "reality" / "live" / "__init__.py").unlink()
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"root-main": workspace},
    )
    view = result["lineage_effective_views"]["root-main"]
    python_path = Path(view["effective_python_path"])

    assert view["lineage_id"] == "root-main"
    assert view["workspace_key"] == "root-main"
    assert Path(view["private_effective_live_root"]) == (
        workspace.resolve() / ".xinao-world-runtime" / "live-reality"
    )
    assert not (python_path / "xinao_legacy_research" / "__init__.py").exists()
    imported = _import_probe(
        python_path,
        "xinao_legacy_research.standalone",
        view["runtime_environment"],
    )
    assert imported.returncode == 0
    assert imported.stdout.strip() == "still-present"
    assert "__init__.py" in {deletion["relative_path"] for deletion in view["deletions"]}


def test_complete_clone_without_live_tree_records_520_deletions_and_empty_view(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    canonical_live = repo / "xinao" / "reality" / "live"
    for index in range(511):
        _write(canonical_live / "bulk" / f"artifact-{index:03d}.json", b"{}\n")
    workspace = tmp_path / "world-01"
    workspace.mkdir()
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )

    assert len(result["lineage_effective_views"]) == 1
    sample = result["lineage_effective_views"]["world-01"]
    python_path = Path(sample["effective_python_path"])
    assert list(python_path.rglob("*.py")) == []
    assert _snapshot(Path(sample["effective_code_root"])) == {}
    private_root = Path(sample["private_effective_live_root"])
    assert [path.name for path in private_root.iterdir()] == [".xinao-private-live-origin.json"]
    assert sample["deletion_count"] == 520
    assert len(sample["deletions"]) == 520


def test_rerun_preserves_evolving_private_live_state_and_lineages_do_not_leak(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace_a = _make_complete_clone(tmp_path / "world-01", repo)
    workspace_b = _make_complete_clone(tmp_path / "world-02", repo)
    live_target = tmp_path / "runtime" / "live"
    compute_target = tmp_path / "runtime" / "compute"
    first = migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
        workspace_roots={"world-01": workspace_a, "world-02": workspace_b},
    )
    private_a = Path(first["lineage_effective_views"]["world-01"]["private_effective_live_root"])
    private_b = Path(first["lineage_effective_views"]["world-02"]["private_effective_live_root"])
    code_a = Path(first["lineage_effective_views"]["world-01"]["effective_code_root"])
    code_b = Path(first["lineage_effective_views"]["world-02"]["effective_code_root"])
    assert code_a != code_b
    current_a = private_a / "pre203_holdout_fixture" / "CURRENT.json"
    current_b = private_b / "pre203_holdout_fixture" / "CURRENT.json"
    current_a.write_bytes(b'{"turn":2}\n')
    _write(private_a / "runtime-only" / "event.json", b'{"lineage":"a"}\n')
    a_before = _snapshot(private_a)
    b_before = _snapshot(private_b)

    second = migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
        workspace_roots={"world-02": workspace_b, "world-01": workspace_a},
    )

    assert second["private_live_dispositions"] == {
        "world-01": "preserved_existing_mutable_state",
        "world-02": "preserved_existing_mutable_state",
    }
    assert second["manifest_sha256"] == first["manifest_sha256"]
    assert second["manifest_disposition"] == "verified_existing"
    assert _snapshot(private_a) == a_before
    assert _snapshot(private_b) == b_before
    assert current_a.read_bytes() == b'{"turn":2}\n'
    assert current_b.read_bytes() != current_a.read_bytes()
    assert not (private_b / "runtime-only" / "event.json").exists()
    _write(code_a / "code" / "xinao_legacy_research" / "lineage-a-only.py", b"VALUE = 1\n")
    assert not (code_b / "code" / "xinao_legacy_research" / "lineage-a-only.py").exists()


def test_readback_rejects_extra_effective_file_but_allows_private_mutation(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = _make_complete_clone(tmp_path / "world-01", repo)
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )
    view = result["lineage_effective_views"]["world-01"]
    _write(Path(view["private_effective_live_root"]) / "consumer-state.json", b"{}\n")
    assert (
        readback_live_reality_migration(
            Path(result["manifest_path"]),
            expected_manifest_sha256=result["manifest_sha256"],
        )["status"]
        == "verified"
    )
    _write(
        Path(view["effective_python_path"]) / "xinao_legacy_research" / "stale.py",
        b"VALUE = 1\n",
    )
    with pytest.raises(RealityMigrationError, match="is not exhaustive"):
        readback_live_reality_migration(
            Path(result["manifest_path"]),
            expected_manifest_sha256=result["manifest_sha256"],
        )


def test_readback_rejects_runtime_binding_inputs_that_do_not_match_view(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = _make_complete_clone(tmp_path / "world-01", repo)
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )
    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workspace_overlays"][0]["runtime_binding_inputs"]["private_live_root"] = str(
        tmp_path / "wrong-lineage"
    )
    raw = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    manifest_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    manifest_path.with_suffix(".sha256").write_text(
        f"{digest}  {manifest_path.name}\n", encoding="ascii"
    )

    with pytest.raises(RealityMigrationError, match="runtime binding inputs mismatch"):
        readback_live_reality_migration(
            manifest_path,
            expected_manifest_sha256=digest,
            verify_sources=False,
        )


def test_readback_rejects_resealed_view_identity_that_drops_binding_identity(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = _make_complete_clone(tmp_path / "world-01", repo)
    result = migrate_live_reality_copy_first(
        repo,
        live_reality_root=tmp_path / "runtime" / "live",
        world_compute_root=tmp_path / "runtime" / "compute",
        workspace_roots={"world-01": workspace},
    )
    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workspace_overlays"][0]["effective_view_id"] = "0" * 64
    raw = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    manifest_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    manifest_path.with_suffix(".sha256").write_text(
        f"{digest}  {manifest_path.name}\n", encoding="ascii"
    )

    with pytest.raises(RealityMigrationError, match="effective view manifest contract mismatch"):
        readback_live_reality_migration(
            manifest_path,
            expected_manifest_sha256=digest,
            verify_sources=False,
        )


def test_changed_seed_for_existing_private_lineage_fails_before_target_mutation(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    workspace = _make_complete_clone(tmp_path / "world-01", repo)
    live_target = tmp_path / "runtime" / "live"
    compute_target = tmp_path / "runtime" / "compute"
    migrate_live_reality_copy_first(
        repo,
        live_reality_root=live_target,
        world_compute_root=compute_target,
        workspace_roots={"world-01": workspace},
    )
    target_before = {
        "live": _snapshot(live_target),
        "compute": _snapshot(compute_target),
    }
    _write(
        workspace / "xinao" / "reality" / "live" / "pre203_holdout_fixture" / "CURRENT.json",
        b'{"turn":2}\n',
    )

    with pytest.raises(RealityMigrationError, match="initialization identity mismatch"):
        migrate_live_reality_copy_first(
            repo,
            live_reality_root=live_target,
            world_compute_root=compute_target,
            workspace_roots={"world-01": workspace},
        )
    assert _snapshot(live_target) == target_before["live"]
    assert _snapshot(compute_target) == target_before["compute"]


def _retirement_runtime_fixture(
    tmp_path: Path, repo: Path, request: pytest.FixtureRequest
) -> tuple[list[Path], list[Path], list[Path], list[subprocess.Popen[bytes]]]:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _write(repo / ".gitignore", b"xinao/reality/live/\n")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    active_configs: list[Path] = []
    stopped_preparations: list[Path] = []
    manifests: list[Path] = []
    controllers: list[subprocess.Popen[bytes]] = []
    lineage_counts = (3, 5, 3, 5, 5, 9, 5, 9)
    account_slots = ("A", "C", "A", "A", "C", "A", "C", "C")
    for index, (workspace_count, account_slot) in enumerate(
        zip(lineage_counts, account_slots, strict=True)
    ):
        workspaces: dict[str, Path] = {}
        for lineage_index in range(workspace_count):
            lineage_id = f"lineage-{index:02d}-{lineage_index:02d}"
            workspace = tmp_path / f"run-{index:02d}" / lineage_id
            workspace.mkdir(parents=True)
            shutil.copytree(
                repo / "xinao" / "reality" / "live",
                workspace / "xinao" / "reality" / "live",
            )
            workspaces[lineage_id] = workspace
        result = migrate_live_reality_copy_first(
            repo,
            live_reality_root=tmp_path / "runtime" / "live",
            world_compute_root=tmp_path / "runtime" / f"run-{index:02d}",
            workspace_roots=workspaces,
        )
        manifest_path = Path(result["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_id = f"run-{index:02d}"
        run_root = tmp_path / "state" / f"runtime-{index:02d}"
        run_dir = run_root / "runs" / run_id
        config_path = run_dir / "run_config.json"
        views: dict[str, dict[str, object]] = {}
        for overlay in manifest["workspace_overlays"]:
            private = overlay["private_live_materialization"]
            lineage_id = overlay["workspace_key"]
            views[lineage_id] = {
                "workspace": str(Path(overlay["workspace_root"]).resolve()),
                "base_manifest_path": manifest["base_bundle"]["manifest_path"],
                "base_manifest_sha256": manifest["base_bundle"]["manifest_sha256"],
                "effective_code_root": overlay["effective_code_root"],
                "effective_python_path": overlay["effective_python_path"],
                "effective_code_manifest_path": overlay["effective_code_manifest_path"],
                "effective_code_manifest_sha256": overlay["effective_code_manifest_sha256"],
                "effective_code_tree_sha256": overlay["effective_code_payload_tree_sha256"],
                "private_live_root": overlay["private_effective_live_root"],
                "live_seed_receipt_path": private["receipt_path"],
                "live_seed_receipt_sha256": private["receipt_sha256"],
            }
        controller_raw = b"import time\ntime.sleep(300)\n"
        config = {
            "schema": "test.runtime.v1",
            "run_id": run_id,
            "account_slot": account_slot,
            "source_repo": str(repo.resolve()),
            "source_head": "a" * 40,
            "runtime_binding_required": True,
            "controller_python": str(Path(sys.executable).resolve()),
            "controller_python_sha256": hashlib.sha256(
                Path(sys.executable).read_bytes()
            ).hexdigest(),
            "controller_release_path": str(run_dir / "controller_release.py"),
            "controller_release_sha256": hashlib.sha256(controller_raw).hexdigest(),
            "runtime_binding_views": views,
            "reality_migration_manifest_path": str(manifest_path),
            "reality_migration_manifest_sha256": result["manifest_sha256"],
            "reality_migration_id": result["migration_id"],
        }
        _write(run_dir / "controller_release.py", controller_raw)
        _write(config_path, _canonical_test_json(config))
        pointer_path = run_root / "current.json"
        controller = subprocess.Popen(
            [
                sys.executable,
                str(run_dir / "controller_release.py"),
                "run",
                "--config",
                str(config_path),
            ]
        )
        controllers.append(controller)
        pointer = {
            "schema": "test.pointer.v1",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "account_slot": account_slot,
            "controller_pid": controller.pid,
            "controller_release_path": str(run_dir / "controller_release.py"),
            "controller_release_sha256": hashlib.sha256(controller_raw).hexdigest(),
        }
        _write(pointer_path, _canonical_test_json(pointer))
        _write(
            run_dir / "controller_state.json",
            _canonical_test_json(
                {"schema": "test.controller.v1", "status": "RUNNING", "pid": os.getpid()}
            ),
        )
        state = json.loads((run_dir / "controller_state.json").read_text(encoding="utf-8"))
        state["pid"] = controller.pid
        _write(run_dir / "controller_state.json", _canonical_test_json(state))
        active_configs.append(config_path)
        manifests.append(manifest_path)

    for stopped_index, (account_slot, workspace_count) in enumerate((("A", 3), ("C", 5))):
        index = 8 + stopped_index
        workspaces: dict[str, Path] = {}
        for lineage_index in range(workspace_count):
            lineage_id = f"lineage-{index:02d}-{lineage_index:02d}"
            workspace = tmp_path / f"run-{index:02d}" / lineage_id
            workspace.mkdir(parents=True)
            shutil.copytree(
                repo / "xinao" / "reality" / "live",
                workspace / "xinao" / "reality" / "live",
            )
            workspaces[lineage_id] = workspace
        result = migrate_live_reality_copy_first(
            repo,
            live_reality_root=tmp_path / "runtime" / "live",
            world_compute_root=tmp_path / "runtime" / f"run-{index:02d}",
            workspace_roots=workspaces,
        )
        manifest_path = Path(result["manifest_path"])
        run_id = f"run-{index:02d}"
        runtime_root = tmp_path / "state" / f"runtime-{index:02d}"
        run_dir = runtime_root / "runs" / run_id
        config_path = run_dir / "run_config.json"
        config = {
            "schema": "test.runtime.v1",
            "run_id": run_id,
            "account_slot": account_slot,
            "source_repo": str(repo.resolve()),
            "source_head": "a" * 40,
        }
        _write(config_path, _canonical_test_json(config))
        pointer_path = runtime_root / "current.json"
        pointer = {
            "schema": "test.pointer.v1",
            "run_id": run_id,
            "run_dir": str(run_dir),
            "account_slot": account_slot,
            "controller_pid": 0,
        }
        _write(pointer_path, _canonical_test_json(pointer))
        _write(
            run_dir / "controller_state.json",
            _canonical_test_json(
                {
                    "schema": "test.controller.v1",
                    "status": "STOPPED",
                    "pid": 0,
                    "active_processes": {},
                }
            ),
        )
        _write(
            run_dir / "STOP.json",
            _canonical_test_json(
                {"schema": "test.stop.v1", "account_slot": account_slot, "reason": "test"}
            ),
        )
        lineages = [
            {
                "lineage_id": lineage_id,
                "workspace": str(workspace.resolve()),
                "head": "a" * 40,
                "source_head": "a" * 40,
            }
            for lineage_id, workspace in workspaces.items()
        ]
        receipt = {
            "schema": "xinao.cleanroom.world-compute-reality-migration-preparation.v1",
            "status": "PREPARED_NOT_ADOPTED",
            "runtime_root": str(runtime_root),
            "run_id": run_id,
            "account_slot": account_slot,
            "pointer_path": str(pointer_path),
            "pointer_sha256": hashlib.sha256(pointer_path.read_bytes()).hexdigest(),
            "run_config_path": str(config_path),
            "run_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "source": {"root": str(repo.resolve()), "source_head": "a" * 40},
            "lineages": lineages,
            "migration_manifest_path": str(manifest_path),
            "migration_manifest_sha256": result["manifest_sha256"],
            "migration_id": result["migration_id"],
            "run_config_changed": False,
            "current_pointer_changed": False,
            "controller_started": False,
        }
        receipt_path = run_dir / "reality-migration-preparation" / "receipt.json"
        _write(receipt_path, _canonical_test_json(receipt))
        stopped_preparations.append(receipt_path)
        manifests.append(manifest_path)
    request.addfinalizer(lambda: _stop_fixture_controllers(controllers))
    return active_configs, stopped_preparations, manifests, controllers


def _stop_fixture_controllers(controllers: list[subprocess.Popen[bytes]]) -> None:
    for controller in controllers:
        if controller.poll() is None:
            controller.terminate()
    for controller in controllers:
        if controller.poll() is None:
            controller.wait(timeout=10)


def _canonical_test_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_retirement_preserves_exact_source_and_is_idempotent(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    source_before = _snapshot(source)
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    retirement_root = tmp_path / "retirement"

    completed = retire_mixed_live_reality(
        repo,
        active_run_config_paths=active,
        stopped_preparation_paths=stopped,
        retirement_root=retirement_root,
        tracked_repositories=[repo],
    )
    replay = retire_mixed_live_reality(
        repo,
        active_run_config_paths=active,
        stopped_preparation_paths=stopped,
        retirement_root=retirement_root,
        tracked_repositories=[repo],
    )

    assert completed["status"] == "COMPLETED"
    assert replay["retirement_id"] == completed["retirement_id"]
    assert not source.exists()
    assert _snapshot(Path(completed["exact_source_bundle"]["root"]) / "tree") == source_before
    assert len(completed["migrations"]) == 10
    assert sum(item["lineage_count"] for item in completed["migrations"]) == 52
    assert completed["legacy_start_prepare_and_unadopted_recover_require_explicit_restore"]
    assert len(completed["runtime_bindings"]["active"]) == 8
    assert len(completed["runtime_bindings"]["stopped"]) == 2
    restored = restore_retired_mixed_live_reality(
        repo,
        completed_receipt_path=Path(completed["completed_receipt_path"]),
    )
    assert restored["status"] == "RESTORED"
    assert _snapshot(source) == source_before


def test_retirement_recovers_after_rename_without_recapturing_source(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    source_before = _snapshot(source)
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    retirement_root = tmp_path / "retirement"

    def crash(phase: str) -> None:
        if phase == "after_rename":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=retirement_root,
            tracked_repositories=[repo],
            fault_injector=crash,
        )
    assert not source.exists()
    completed = retire_mixed_live_reality(
        repo,
        active_run_config_paths=active,
        stopped_preparation_paths=stopped,
        retirement_root=retirement_root,
        tracked_repositories=[repo],
    )
    assert completed["status"] == "COMPLETED"
    assert _snapshot(Path(completed["exact_source_bundle"]["root"]) / "tree") == source_before


@pytest.mark.parametrize("crash_phase", ["after_delete_authorized", "after_delete"])
def test_retirement_recovers_after_delete_authorization_or_delete(
    tmp_path: Path, crash_phase: str, request: pytest.FixtureRequest
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    source_before = _snapshot(source)
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    retirement_root = tmp_path / "retirement"

    def crash(phase: str) -> None:
        if phase == crash_phase:
            raise RuntimeError(f"simulated {phase}")

    with pytest.raises(RuntimeError, match="simulated"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=retirement_root,
            tracked_repositories=[repo],
            fault_injector=crash,
        )
    completed = retire_mixed_live_reality(
        repo,
        active_run_config_paths=active,
        stopped_preparation_paths=stopped,
        retirement_root=retirement_root,
        tracked_repositories=[repo],
    )
    assert completed["status"] == "COMPLETED"
    assert not source.exists()
    assert _snapshot(Path(completed["exact_source_bundle"]["root"]) / "tree") == source_before


def test_retirement_rejects_tracked_consumer_and_payload_drift(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    _write(repo / "consumer.py", b"import xinao.reality.live\n")
    subprocess.run(["git", "-C", str(repo), "add", "consumer.py"], check=True)
    with pytest.raises(RealityMigrationError, match="consumer absence"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=tmp_path / "blocked-retirement",
            tracked_repositories=[repo],
        )
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "-f", "consumer.py"], check=True)
    _write(source / "new-meaningful.json", b'{"new":true}\n')
    with pytest.raises(RealityMigrationError, match="current meaningful payload"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=tmp_path / "drift-retirement",
            tracked_repositories=[repo],
        )


def test_retirement_rolls_back_rename_when_consumer_acceptance_fails(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    source_before = _snapshot(source)
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)

    def reject() -> None:
        raise RuntimeError("consumer rejected retired source")

    with pytest.raises(RuntimeError, match="consumer rejected"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=tmp_path / "retirement",
            tracked_repositories=[repo],
            post_rename_validator=reject,
        )
    assert _snapshot(source) == source_before


def test_retirement_rolls_back_when_post_rename_runtime_readback_fails(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    source_before = _snapshot(source)
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    real_validate = reality_migration_module.validate_retirement_runtime_bindings
    call_count = 0

    def fail_third_readback(**kwargs: object) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise RuntimeError("post-rename runtime readback failed")
        return real_validate(**kwargs)

    monkeypatch.setattr(
        reality_migration_module,
        "validate_retirement_runtime_bindings",
        fail_third_readback,
    )
    with pytest.raises(RuntimeError, match="post-rename runtime readback failed"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=tmp_path / "retirement",
            tracked_repositories=[repo],
        )
    assert _snapshot(source) == source_before


def test_retirement_replays_prepared_after_dynamic_controller_state_changes(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    repo = _make_repo(tmp_path / "repo")
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    retirement_root = tmp_path / "retirement"

    def crash(phase: str) -> None:
        if phase == "after_prepared":
            raise RuntimeError("simulated after PREPARED")

    with pytest.raises(RuntimeError, match="after PREPARED"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=retirement_root,
            tracked_repositories=[repo],
            fault_injector=crash,
        )
    state_path = active[0].parent / "controller_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["turns_completed"] = 7
    state["updated_at"] = "later-but-same-controller"
    _write(state_path, _canonical_test_json(state))

    completed = retire_mixed_live_reality(
        repo,
        active_run_config_paths=active,
        stopped_preparation_paths=stopped,
        retirement_root=retirement_root,
        tracked_repositories=[repo],
    )
    assert completed["status"] == "COMPLETED"


def test_delete_authorization_recovers_from_partial_rmtree(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path / "repo")
    active, stopped, _, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    retirement_root = tmp_path / "retirement"
    real_rmtree = shutil.rmtree
    failed = False

    def partial_rmtree(path: object, *args: object, **kwargs: object) -> None:
        nonlocal failed
        target = Path(path)
        if not failed and target.name.startswith(".live.retiring-"):
            first_file = next(item for item in target.rglob("*") if item.is_file())
            first_file.unlink()
            failed = True
            raise OSError("simulated partial rmtree")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(reality_migration_module.shutil, "rmtree", partial_rmtree)
    with pytest.raises(OSError, match="partial rmtree"):
        retire_mixed_live_reality(
            repo,
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            retirement_root=retirement_root,
            tracked_repositories=[repo],
        )
    monkeypatch.setattr(reality_migration_module.shutil, "rmtree", real_rmtree)

    completed = retire_mixed_live_reality(
        repo,
        active_run_config_paths=active,
        stopped_preparation_paths=stopped,
        retirement_root=retirement_root,
        tracked_repositories=[repo],
    )
    assert completed["status"] == "COMPLETED"
    assert not (repo / "xinao" / "reality" / "live").exists()


def test_runtime_binding_set_rejects_old_stopped_manifest_substitution(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    repo = _make_repo(tmp_path / "repo")
    active, stopped, manifests, _controllers = _retirement_runtime_fixture(tmp_path, repo, request)
    receipt = json.loads(stopped[0].read_text(encoding="utf-8"))
    receipt["migration_manifest_path"] = str(manifests[0])
    receipt["migration_manifest_sha256"] = hashlib.sha256(manifests[0].read_bytes()).hexdigest()
    _write(stopped[0], _canonical_test_json(receipt))

    with pytest.raises(RealityMigrationError, match="stopped preparation runtime mismatch"):
        validate_retirement_runtime_bindings(
            active_run_config_paths=active,
            stopped_preparation_paths=stopped,
            canonical_repo=repo,
        )


def test_consumer_observer_excludes_migration_contract_but_finds_runtime_source(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _write(
        repo / "services" / "xinao_perpetual_world_compute" / "reality_migration.py",
        b"xinao/reality/live\n",
    )
    _write(repo / "consumer.py", b"import xinao.reality.live\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    observed = observe_mixed_live_retirement_consumers(source, tracked_repositories=[repo])

    assert observed["tracked_scan_complete"] is True
    assert observed["tracked_runtime_consumer_matches"] == 1
    assert observed["tracked_matches"][0]["relative_path"] == "consumer.py"


def test_consumer_observer_keeps_fixed_historical_references_without_runtime_block(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    source = repo / "xinao" / "reality" / "live"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    historical = repo / "xinao" / "cognition" / "root_package_relation_field" / "俩仓库.txt"
    _write(historical, b"historical xinao/reality/live locator\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    observed = observe_mixed_live_retirement_consumers(source, tracked_repositories=[repo])

    assert observed["tracked_runtime_consumer_matches"] == 0
    assert observed["tracked_historical_reference_matches"] == 1
