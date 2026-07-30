"""One-home canonical updater + SI operational CAS projection tests."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from xinao.tool_glue import canonical_paths, operational_projection, publication
from xinao.tool_glue import projection_binding_verifier as binding_verifier

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_SCRIPT = REPO_ROOT / "scripts" / "Update-CodexContextCatalog.ps1"
PACKAGE_ROOT = REPO_ROOT / "xinao_discovery"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _try_symlink(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    """Create a real symlink or skip when the environment forbids it."""

    try:
        if target_is_directory:
            link.symlink_to(target, target_is_directory=True)
        else:
            link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink unavailable in this environment: {exc}")


def _is_reparse_leaf(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def test_canonical_updater_is_package_local_not_parents_walk() -> None:
    canonical = canonical_paths.discover_canonical_updater_path()
    assert canonical.is_file()
    assert canonical.parent.name == "resources"
    # No parents[N]-style resolution: path is under the installed package tree.
    assert "xinao" in canonical.parts
    assert "tool_glue" in canonical.parts
    source = Path(publication.__file__).read_text(encoding="utf-8")
    assert ".parents[" not in source
    # Default updater identity is the SI operational entry constant.
    assert str(publication.DEFAULT_UPDATER_PATH).endswith(
        str(Path("Codex_Situation_Island") / "scripts" / "Update-CodexContextCatalog.ps1")
    )


def test_checkout_scripts_alias_matches_canonical_same_byte() -> None:
    canonical = canonical_paths.discover_canonical_updater_path()
    assert CHECKOUT_SCRIPT.is_file()
    assert _sha256(CHECKOUT_SCRIPT) == _sha256(canonical)


def test_resolve_production_updater_fails_closed_on_foreign_bytes(tmp_path: Path) -> None:
    island = tmp_path / "island"
    scripts = island / "scripts"
    scripts.mkdir(parents=True)
    foreign = scripts / "Update-CodexContextCatalog.ps1"
    foreign.write_text("# foreign operational bytes\n", encoding="utf-8")
    with pytest.raises(canonical_paths.CanonicalPathError) as raised:
        canonical_paths.resolve_production_updater_path(island_root=island)
    assert raised.value.code == "OPERATIONAL_UPDATER_DRIFT"


def test_install_promote_recover_rollback_operational_updater(tmp_path: Path) -> None:
    island = tmp_path / "island"
    state_root = tmp_path / "op-state"
    scripts = island / "scripts"
    scripts.mkdir(parents=True)
    operational = scripts / "Update-CodexContextCatalog.ps1"
    operational.write_bytes(b"# old operational foreign bytes\n")
    old_digest = _sha256(operational)
    canonical = canonical_paths.discover_canonical_updater_path()
    new_digest = _sha256(canonical)

    installed = operational_projection.install_operational_updater(
        island_root=island,
        state_root=state_root,
        expected_old_sha256=old_digest,
        transaction_id="tx-install-1",
    )
    assert installed["status"] == publication.VERIFIED
    assert installed["expected_new_sha256"] == new_digest
    assert _sha256(operational) == new_digest
    assert installed.get("already_same_byte") is not True

    # Idempotent same-byte reinstall does not open a new mutation journal.
    again = operational_projection.install_operational_updater(
        island_root=island,
        state_root=state_root,
    )
    assert again["status"] == publication.VERIFIED
    assert again["already_same_byte"] is True

    # Explicit rollback restores preimage.
    journal_path = Path(str(installed["journal_path"]))
    rolled = operational_projection.rollback_operational_updater(
        journal_path=journal_path,
        island_root=island,
        state_root=state_root,
    )
    assert rolled["status"] == publication.ROLLED_BACK_VERIFIED
    assert _sha256(operational) == old_digest

    # Recover with no active marker is a no-op.
    recovered = operational_projection.recover_operational_updater(
        island_root=island,
        state_root=state_root,
    )
    assert recovered["status"] == "NO_INTERRUPTED_TRANSACTION"


def test_install_create_when_missing_and_foreign_byte_block(tmp_path: Path) -> None:
    island = tmp_path / "island"
    state_root = tmp_path / "op-state"
    canonical = canonical_paths.discover_canonical_updater_path()
    new_digest = _sha256(canonical)

    created = operational_projection.install_operational_updater(
        island_root=island,
        state_root=state_root,
        transaction_id="tx-create-1",
    )
    operational = island / "scripts" / "Update-CodexContextCatalog.ps1"
    assert created["status"] == publication.VERIFIED
    assert _sha256(operational) == new_digest

    # Simulate interrupted APPLYING with foreign bytes at operational path.
    marker = state_root / "active_transaction.marker.json"
    journal_path = state_root / "transactions" / "tx-foreign" / "transaction.v1.json"
    journal_path.parent.mkdir(parents=True)
    foreign = b"# completely foreign interrupted bytes\n"
    operational.write_bytes(foreign)
    journal = {
        "schema_version": operational_projection.JOURNAL_SCHEMA,
        "transaction_id": "tx-foreign",
        "status": publication.APPLYING,
        "artifact_kind": operational_projection.ARTIFACT_KIND,
        "island_root": str(island.resolve()),
        "operational_path": str(operational.resolve()),
        "canonical_path": str(canonical),
        "expected_old_sha256": new_digest,
        "expected_new_sha256": "a" * 64,
        "candidate_archive_path": None,
        "preimage_archive_path": None,
        "authority_metadata": None,
        "completion_claim_allowed": False,
    }
    journal_path.write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")
    marker.write_text(
        json.dumps(
            {
                "schema_version": operational_projection.MARKER_SCHEMA,
                "operational_path": str(operational.resolve()),
                "journal_path": str(journal_path.resolve()),
                "transaction_id": "tx-foreign",
                "status": publication.APPLYING,
                "completion_claim_allowed": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(publication.PublicationError) as raised:
        operational_projection.recover_operational_updater(
            island_root=island,
            state_root=state_root,
        )
    assert raised.value.code == "FOREIGN_BYTE_BLOCK"
    assert operational.read_bytes() == foreign


def test_projection_binding_verifier_requires_version(tmp_path: Path) -> None:
    authority = tmp_path / "authority.txt"
    authority.write_text(
        "软件工具胶水宪法｜当前有效\n版本：v3.4\nSENTINEL:XINAO_SOFTWARE_TOOL_GLUE_CONSTITUTION_V2\n",
        encoding="utf-8",
    )
    digest = _sha256(authority)
    projection = tmp_path / "active_parent.current.json"
    projection.write_text(
        json.dumps(
            {
                "software_foundation": {
                    "path": str(authority),
                    "sha256": digest,
                    # version deliberately omitted
                }
            }
        ),
        encoding="utf-8",
    )
    island = tmp_path / "island"
    operational_projection.install_operational_updater(
        island_root=island,
        state_root=tmp_path / "op-state",
    )
    map_path = tmp_path / "map.json"
    map_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "catalog_updater",
                        "path": str(island / "scripts" / "Update-CodexContextCatalog.ps1"),
                        "sha256": _sha256(
                            island / "scripts" / "Update-CodexContextCatalog.ps1"
                        ).upper(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    receipt = binding_verifier.verify_projection_bindings(
        authority_path=authority,
        science_projection_path=projection,
        maintenance_map_path=map_path,
        island_root=island,
        expected_sha256=digest,
        expected_version="v3.4",
    )
    assert receipt["ready"] is False
    assert "SOFTWARE_FOUNDATION_VERSION_MISMATCH" in receipt["failed"]

    # Bind version and re-verify.
    payload = json.loads(projection.read_text(encoding="utf-8"))
    payload["software_foundation"]["version"] = "v3.4"
    projection.write_text(json.dumps(payload), encoding="utf-8")
    ok = binding_verifier.verify_projection_bindings(
        authority_path=authority,
        science_projection_path=projection,
        maintenance_map_path=map_path,
        island_root=island,
        expected_sha256=digest,
        expected_version="v3.4",
    )
    assert ok["ready"] is True
    assert ok["failed"] == []
    assert ok["software_foundation_version"] == "v3.4"
    assert ok["software_foundation_sha256"] == digest


def test_projection_binding_verifier_fresh_process(tmp_path: Path) -> None:
    authority = tmp_path / "authority.txt"
    authority.write_text(
        "软件工具胶水宪法｜当前有效\n版本：v3.4\nSENTINEL:XINAO_SOFTWARE_TOOL_GLUE_CONSTITUTION_V2\n",
        encoding="utf-8",
    )
    digest = _sha256(authority)
    island = tmp_path / "island"
    operational_projection.install_operational_updater(
        island_root=island,
        state_root=tmp_path / "op-state",
    )
    operational = island / "scripts" / "Update-CodexContextCatalog.ps1"
    projection = tmp_path / "active_parent.current.json"
    projection.write_text(
        json.dumps(
            {
                "software_foundation": {
                    "path": str(authority),
                    "sha256": digest,
                    "version": "v3.4",
                }
            }
        ),
        encoding="utf-8",
    )
    map_path = tmp_path / "map.json"
    map_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "catalog_updater",
                        "path": str(operational),
                        "sha256": _sha256(operational).upper(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(canonical_paths.discover_projection_binding_verifier_path()),
            "--authority-path",
            str(authority),
            "--science-projection-path",
            str(projection),
            "--maintenance-map-path",
            str(map_path),
            "--island-root",
            str(island),
            "--expected-sha256",
            digest,
            "--expected-version",
            "v3.4",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    receipt = json.loads(completed.stdout)
    assert receipt["ready"] is True
    assert receipt["software_foundation_version"] == "v3.4"


def test_canonical_updater_resource_present_in_disposable_wheel(tmp_path: Path) -> None:
    import os
    import shutil

    dist = tmp_path / "dist"
    dist.mkdir()
    env = dict(os.environ)
    env["HATCH_BUILD_CLEAN"] = "true"
    # Disposable wheel via uvx-hosted hatchling (venv may lack pip/hatchling).
    completed = subprocess.run(
        ["uvx", "--from", "hatchling==1.28.0", "hatchling", "build", "--target", "wheel"],
        cwd=str(PACKAGE_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=180,
        env=env,
    )
    project_dist = PACKAGE_ROOT / "dist"
    wheels = list(project_dist.glob("*.whl")) if project_dist.is_dir() else []
    if completed.returncode != 0 or not wheels:
        pytest.fail(
            "disposable wheel build failed: "
            f"rc={completed.returncode} stdout={completed.stdout[-2000:]} "
            f"stderr={completed.stderr[-2000:]}"
        )
    wheel = max(wheels, key=lambda path: path.stat().st_mtime)
    disposable = dist / wheel.name
    shutil.copy2(wheel, disposable)
    for artifact in project_dist.glob("*.whl"):
        try:
            artifact.unlink()
        except OSError:
            pass
    with zipfile.ZipFile(disposable) as archive:
        names = archive.namelist()
    resource_names = [
        name
        for name in names
        if name.replace("\\", "/").endswith(
            "xinao/tool_glue/resources/Update-CodexContextCatalog.ps1"
        )
    ]
    assert resource_names, f"canonical updater missing from wheel; sample={names[:40]}"
    assert any(
        name.replace("\\", "/").endswith("xinao/tool_glue/projection_binding_verifier.py")
        for name in names
    )
    assert any(
        name.replace("\\", "/").endswith("xinao/tool_glue/resources/verify_tool_glue_consumer.py")
        for name in names
    )


def test_catalog_updater_fixture_still_uses_checkout_script(tmp_path: Path) -> None:
    """Behavior regression: package resource and checkout script stay executable."""
    assert CHECKOUT_SCRIPT.is_file()
    assert _sha256(CHECKOUT_SCRIPT) == _sha256(canonical_paths.discover_canonical_updater_path())


def test_install_rejects_symlink_operational_leaf_before_target_mutation(
    tmp_path: Path,
) -> None:
    """Symlink/reparse operational leaf fails closed; foreign target bytes stay intact."""

    island = tmp_path / "island"
    state_root = tmp_path / "op-state"
    scripts = island / "scripts"
    scripts.mkdir(parents=True)
    foreign = tmp_path / "FOREIGN_TARGET.ps1"
    foreign_bytes = b"# FOREIGN SHOULD NOT BE MUTATED\n"
    foreign.write_bytes(foreign_bytes)
    foreign_digest = _sha256_bytes(foreign_bytes)
    leaf = scripts / "Update-CodexContextCatalog.ps1"
    _try_symlink(leaf, foreign)

    assert leaf.is_symlink()
    assert _is_reparse_leaf(leaf)
    before_link_lstat = leaf.lstat()

    with pytest.raises(publication.PublicationError) as raised:
        operational_projection.install_operational_updater(
            island_root=island,
            state_root=state_root,
            transaction_id="tx-reparse-leaf",
        )
    assert raised.value.code == "OPERATIONAL_UPDATER_REPARSE"
    assert leaf.is_symlink()
    assert _is_reparse_leaf(leaf)
    assert leaf.readlink() == foreign or os.path.samefile(leaf.readlink(), foreign)
    assert foreign.read_bytes() == foreign_bytes
    assert _sha256(foreign) == foreign_digest
    # Literal leaf identity unchanged (still a reparse; not replaced by plain file).
    assert leaf.lstat().st_ino == before_link_lstat.st_ino or leaf.is_symlink()
    assert not (state_root / "active_transaction.marker.json").exists()


def test_atomic_replace_rejects_reparse_leaf_without_following(tmp_path: Path) -> None:
    """Defense in depth: replace helper must not resolve through a reparse leaf."""

    target = tmp_path / "foreign.ps1"
    foreign_bytes = b"# replace must not touch me\n"
    target.write_bytes(foreign_bytes)
    link = tmp_path / "leaf.ps1"
    _try_symlink(link, target)
    with pytest.raises(publication.PublicationError) as raised:
        publication._atomic_replace_bytes(link, b"# new bytes that must not land on target\n")
    assert raised.value.code == "REPLACE_TARGET_REPARSE"
    assert link.is_symlink()
    assert target.read_bytes() == foreign_bytes
    assert _sha256(target) == _sha256_bytes(foreign_bytes)


def test_directory_reparse_scripts_escape_rejected(tmp_path: Path) -> None:
    """Directory reparse under scripts/ must not escape island containment."""

    island = tmp_path / "island"
    island.mkdir()
    foreign_dir = tmp_path / "foreign_scripts"
    foreign_dir.mkdir()
    foreign_leaf = foreign_dir / "Update-CodexContextCatalog.ps1"
    foreign_bytes = b"# escaped foreign operational bytes\n"
    foreign_leaf.write_bytes(foreign_bytes)
    foreign_digest = _sha256(foreign_leaf)
    scripts = island / "scripts"
    _try_symlink(scripts, foreign_dir, target_is_directory=True)

    with pytest.raises(publication.PublicationError) as raised:
        operational_projection.install_operational_updater(
            island_root=island,
            state_root=tmp_path / "op-state",
            transaction_id="tx-dir-reparse",
        )
    assert raised.value.code == "OPERATIONAL_PARENT_REPARSE"
    assert scripts.is_symlink() or _is_reparse_leaf(scripts)
    assert foreign_leaf.read_bytes() == foreign_bytes
    assert _sha256(foreign_leaf) == foreign_digest


def test_hardlink_peer_still_isolated_after_reparse_guards(tmp_path: Path) -> None:
    """Hardlink isolation remains: replace operational name without mutating peer bytes."""

    island = tmp_path / "island"
    state_root = tmp_path / "op-state"
    scripts = island / "scripts"
    scripts.mkdir(parents=True)
    operational = scripts / "Update-CodexContextCatalog.ps1"
    peer = tmp_path / "hardlink_peer.ps1"
    peer_bytes = b"# shared preimage hardlink\n"
    peer.write_bytes(peer_bytes)
    peer_digest = _sha256_bytes(peer_bytes)
    os.link(peer, operational)
    canonical = canonical_paths.discover_canonical_updater_path()
    installed = operational_projection.install_operational_updater(
        island_root=island,
        state_root=state_root,
        transaction_id="tx-hardlink",
    )
    assert installed["status"] == publication.VERIFIED
    assert _sha256(operational) == _sha256(canonical)
    assert peer.read_bytes() == peer_bytes
    assert _sha256(peer) == peer_digest
    assert not operational.is_symlink()
