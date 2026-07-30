"""Tests for isolated pure-v1 legacy-migration proof preparation (Wave 9c candidate).

Synthetic fixtures only. No live state, credentials, Docker, or provider calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "recovery" / "Prepare-XinaoIsolatedLegacyMigrationProof.ps1"

LEGACY_POINTER_SCHEMA = "xinao.researcher_current_pointer.v1"
LEGACY_RELEASE_SCHEMA = "xinao.researcher_release.v1"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_text(path: Path, text: str, *, newline: bytes = b"\n") -> None:
    payload = text.encode("utf-8")
    if newline == b"\r\n":
        payload = payload.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    elif newline == b"\n":
        payload = payload.replace(b"\r\n", b"\n")
    _write_bytes(path, payload)


def _find_pwsh() -> str:
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            return path
    pytest.skip("PowerShell is unavailable")


def _run_helper(
    args: list[str],
    *,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    shell = _find_pwsh()
    cmd = [shell, "-NoLogo", "-NoProfile", "-File", str(HELPER), *args]
    run_env = os.environ.copy()
    # Never inherit force-fail / inject hooks unless the test sets them.
    run_env.pop("XINAO_TEST_FORCE_HARDLINK_PROBE_FAILURE", None)
    run_env.pop("XINAO_TEST_MUTATE_RENDERING_AFTER_PREFLIGHT", None)
    if env:
        run_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        env=run_env,
    )


def _combined_output(completed: subprocess.CompletedProcess[str]) -> str:
    return completed.stderr + completed.stdout


def _assert_fail_code(completed: subprocess.CompletedProcess[str], code: str) -> None:
    blob = _combined_output(completed)
    assert completed.returncode != 0, blob
    assert code in blob, f"expected fail code {code!r} in:\n{blob}"


def _skill_tree(root: Path, *, newline: bytes, marker: str) -> None:
    files = {
        "SKILL.md": f"# skill\nmarker={marker}\n",
        "scripts/xinao.py": f"print({marker!r})\n",
        "references/capabilities.v1.json": '{"capabilities":[]}\n',
        "references/researcher-charter.v1.json": '{"charter":"v1"}\n',
        "references/researcher-runtime-lock.v1.json": '{"lock":"v1"}\n',
        "references/meta.md": f"meta {marker}\n",
        "references/researcher-output.v1.schema.json": '{"type":"object"}\n',
        "references/migration-marker.txt": f"{marker}\n",
    }
    for rel, text in files.items():
        _write_text(root / rel, text, newline=newline)


def _skill_side_hashes(
    root: Path,
    *,
    dockerfile_path: Path,
    entrypoint_path: Path,
) -> dict[str, str]:
    output_v1 = root / "references" / "researcher-output.v1.schema.json"
    output_v2 = root / "references" / "researcher-output.v2.schema.json"
    if output_v1.is_file():
        output_schema = _sha256_file(output_v1)
    elif output_v2.is_file():
        output_schema = _sha256_file(output_v2)
    else:
        raise AssertionError("output schema missing")
    required = {
        "skill_md_sha256": root / "SKILL.md",
        "skill_invoker_sha256": root / "scripts" / "xinao.py",
        "capability_registry_sha256": root / "references" / "capabilities.v1.json",
        "charter_sha256": root / "references" / "researcher-charter.v1.json",
        "runtime_lock_sha256": root / "references" / "researcher-runtime-lock.v1.json",
        "meta_sha256": root / "references" / "meta.md",
    }
    hashes = {"output_schema_sha256": output_schema}
    for key, path in required.items():
        hashes[key] = _sha256_file(path)
    # Bound to legacy repository docker bytes (not v2 candidate).
    hashes["dockerfile_sha256"] = _sha256_file(dockerfile_path)
    hashes["entrypoint_sha256"] = _sha256_file(entrypoint_path)
    return hashes


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _write_bytes(path, _canonical_json(value))


def _release_manifest(
    release_id: str, skill_hashes: dict[str, str], *, image_char: str
) -> dict[str, Any]:
    source_identity = {
        "source_commit": "b916f8bd22dd38b4807298a4c935f6bf2969eb13",
        "source_tree": "71f8994c8e8e8f10c09cf8aef3e21ba3635d627e",
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "capability_registry_sha256": skill_hashes["capability_registry_sha256"],
        "charter_sha256": skill_hashes["charter_sha256"],
        "dockerfile_sha256": skill_hashes["dockerfile_sha256"],
        "entrypoint_sha256": skill_hashes["entrypoint_sha256"],
        "meta_sha256": skill_hashes["meta_sha256"],
        "output_schema_sha256": skill_hashes["output_schema_sha256"],
        "runtime_lock_sha256": skill_hashes["runtime_lock_sha256"],
        "skill_invoker_sha256": skill_hashes["skill_invoker_sha256"],
        "skill_md_sha256": skill_hashes["skill_md_sha256"],
    }
    return {
        "schema_version": LEGACY_RELEASE_SCHEMA,
        "release_id": release_id,
        "created_at": "2026-07-29T07:40:23.273627Z",
        "generic_worker_route_allowed": False,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_id": "sha256:" + image_char * 64,
        "image_labels": {
            "io.xinao.researcher.chain": "dedicated-xinao-science",
            "io.xinao.researcher.generic-worker-route": "forbidden",
            "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        },
        "image_tag_observational": f"xinao-researcher:{release_id}",
        "run_namespace": "xinao_researcher",
        "skill_hashes": skill_hashes,
        "source_identity": source_identity,
        "state_namespace": "xinao_skill/researcher_container",
    }


def _build_world(tmp_path: Path) -> dict[str, Any]:
    live_state = tmp_path / "live_state"
    installed = tmp_path / "installed_skill"
    active_rendering = tmp_path / "renderings" / "active"
    previous_rendering = tmp_path / "renderings" / "previous"
    candidate = tmp_path / "candidate_source"
    active_legacy_repo = tmp_path / "legacy_repos" / "active"
    previous_legacy_repo = tmp_path / "legacy_repos" / "previous"
    approved_base = tmp_path / "approved_proof_base"
    dest = approved_base / "proof-cone-001"

    active_id = "researcher-1.0.0-0a7aea3f2ed52581"
    previous_id = "researcher-1.0.0-4d3458d9901c09b1"

    _skill_tree(active_rendering, newline=b"\r\n", marker="active-rendering")
    _skill_tree(previous_rendering, newline=b"\n", marker="previous-rendering")
    _skill_tree(installed, newline=b"\r\n", marker="installed-drift")
    # Drift installed slightly from active.
    _write_text(
        installed / "SKILL.md",
        (installed / "SKILL.md").read_text(encoding="utf-8") + "# installed-drift\n",
        newline=b"\r\n",
    )

    # Legacy v1 docker/entrypoint provenance (distinct from v2 candidate).
    active_dockerfile = active_legacy_repo / "docker" / "xinao-researcher" / "Dockerfile"
    active_entrypoint = active_legacy_repo / "docker" / "xinao-researcher" / "entrypoint.py"
    previous_dockerfile = previous_legacy_repo / "docker" / "xinao-researcher" / "Dockerfile"
    previous_entrypoint = previous_legacy_repo / "docker" / "xinao-researcher" / "entrypoint.py"
    _write_text(active_dockerfile, "FROM legacy-active-v1\n")
    _write_text(active_entrypoint, "print('legacy-active')\n")
    _write_text(previous_dockerfile, "FROM legacy-previous-v1\n")
    _write_text(previous_entrypoint, "print('legacy-previous')\n")

    active_hashes = _skill_side_hashes(
        active_rendering,
        dockerfile_path=active_dockerfile,
        entrypoint_path=active_entrypoint,
    )
    previous_hashes = _skill_side_hashes(
        previous_rendering,
        dockerfile_path=previous_dockerfile,
        entrypoint_path=previous_entrypoint,
    )

    active_manifest = _release_manifest(active_id, active_hashes, image_char="b")
    previous_manifest = _release_manifest(previous_id, previous_hashes, image_char="a")

    active_path = live_state / "researcher_container" / "releases" / active_id / "release.json"
    previous_path = live_state / "researcher_container" / "releases" / previous_id / "release.json"
    _write_json(active_path, active_manifest)
    _write_json(previous_path, previous_manifest)

    pointer = {
        "schema_version": LEGACY_POINTER_SCHEMA,
        "release_id": active_id,
        "release_manifest_path": str(active_path),
        "release_manifest_sha256": _sha256_file(active_path),
        "promoted_at": "2026-07-29T07:40:23.281374Z",
        "previous_pointer_sha256": "d" * 64,
        "previous_release_id": previous_id,
        "previous_release_manifest_path": str(previous_path),
        "previous_release_manifest_sha256": _sha256_file(previous_path),
    }
    pointer_path = live_state / "researcher_container" / "current.json"
    _write_json(pointer_path, pointer)

    # Candidate v2 source cone (bootstrap invoker shape) — different generation from legacy docker.
    _write_text(candidate / "skills" / "xinao" / "SKILL.md", "# candidate skill v2\n")
    _write_text(candidate / "skills" / "xinao" / "scripts" / "xinao.py", "print('candidate-v2')\n")
    _write_text(
        candidate / "docker" / "xinao-researcher" / "Dockerfile", "FROM scratch\n# v2 candidate\n"
    )
    _write_text(candidate / "docker" / "xinao-researcher" / "entrypoint.py", "print('ok-v2')\n")

    approved_base.mkdir(parents=True, exist_ok=True)

    return {
        "live_state": live_state,
        "installed": installed,
        "active_rendering": active_rendering,
        "previous_rendering": previous_rendering,
        "candidate": candidate,
        "active_legacy_repo": active_legacy_repo,
        "previous_legacy_repo": previous_legacy_repo,
        "approved_base": approved_base,
        "dest": dest,
        "active_id": active_id,
        "previous_id": previous_id,
        "pointer_path": pointer_path,
        "active_path": active_path,
        "previous_path": previous_path,
        "pointer_bytes": pointer_path.read_bytes(),
        "active_bytes": active_path.read_bytes(),
        "previous_bytes": previous_path.read_bytes(),
        "active_skill_md": (active_rendering / "SKILL.md").read_bytes(),
        "previous_skill_md": (previous_rendering / "SKILL.md").read_bytes(),
        "candidate_dockerfile_bytes": (
            candidate / "docker" / "xinao-researcher" / "Dockerfile"
        ).read_bytes(),
        "legacy_active_dockerfile_bytes": active_dockerfile.read_bytes(),
        "installed_snapshot": {
            p.relative_to(installed).as_posix(): p.read_bytes()
            for p in installed.rglob("*")
            if p.is_file()
        },
        "active_rendering_snapshot": {
            p.relative_to(active_rendering).as_posix(): p.read_bytes()
            for p in active_rendering.rglob("*")
            if p.is_file()
        },
        "candidate_snapshot": {
            p.relative_to(candidate).as_posix(): p.read_bytes()
            for p in candidate.rglob("*")
            if p.is_file()
        },
    }


def _prepare_args(world: dict[str, Any], *, dest: Path | None = None) -> list[str]:
    target = dest if dest is not None else world["dest"]
    return [
        "-SourceLiveStateRoot",
        str(world["live_state"]),
        "-SourceInstalledSkillRoot",
        str(world["installed"]),
        "-ActiveSourceRenderingRoot",
        str(world["active_rendering"]),
        "-PreviousSourceRenderingRoot",
        str(world["previous_rendering"]),
        "-DestinationProofRoot",
        str(target),
        "-CandidateSourceRoot",
        str(world["candidate"]),
        "-ActiveLegacyRepositoryRoot",
        str(world["active_legacy_repo"]),
        "-PreviousLegacyRepositoryRoot",
        str(world["previous_legacy_repo"]),
        "-ApprovedProofBase",
        str(world["approved_base"]),
    ]


def _verify_args(world: dict[str, Any], *, dest: Path | None = None) -> list[str]:
    target = dest if dest is not None else world["dest"]
    return [
        "-VerifyOnly",
        "-DestinationProofRoot",
        str(target),
        "-ApprovedProofBase",
        str(world["approved_base"]),
    ]


def _assert_live_unchanged(world: dict[str, Any]) -> None:
    assert world["pointer_path"].read_bytes() == world["pointer_bytes"]
    assert world["active_path"].read_bytes() == world["active_bytes"]
    assert world["previous_path"].read_bytes() == world["previous_bytes"]
    for rel, payload in world["installed_snapshot"].items():
        assert (world["installed"] / rel).read_bytes() == payload
    for rel, payload in world["active_rendering_snapshot"].items():
        assert (world["active_rendering"] / rel).read_bytes() == payload
    for rel, payload in world["candidate_snapshot"].items():
        assert (world["candidate"] / rel).read_bytes() == payload


def _rewrite_receipt(path: Path, mutator) -> None:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    mutator(receipt)
    body = {k: v for k, v in receipt.items() if k != "receipt_content_sha256"}
    body_text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    receipt["receipt_content_sha256"] = _sha256_bytes(body_text.encode("utf-8"))
    path.write_bytes(_canonical_json(receipt))


def test_helper_script_exists() -> None:
    assert HELPER.is_file()
    text = HELPER.read_text(encoding="utf-8")
    assert "completion_claim_allowed" in text
    assert "migration_executed" in text
    assert "live_source_mutated" in text
    assert "XINAO_MIGRATION_SOURCE_ROOT" in text
    assert "VerifyOnly" in text
    assert "HARDLINK_PROBE_FAILED" in text
    assert "ActiveLegacyRepositoryRoot" in text
    assert "candidate-source" in text


def test_prepare_success_crlf_lf_relocation_and_fresh_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    assert b"\r\n" in world["active_skill_md"]
    assert b"\r\n" not in world["previous_skill_md"]
    # v2 candidate docker bytes differ from legacy provenance.
    assert world["candidate_dockerfile_bytes"] != world["legacy_active_dockerfile_bytes"]

    completed = _run_helper(_prepare_args(world))
    assert completed.returncode == 0, completed.stderr + completed.stdout
    summary = json.loads(completed.stdout.strip().splitlines()[-1])
    assert summary["status"] == "PREPARED"
    assert summary["live_source_mutated"] is False
    assert summary["migration_executed"] is False
    assert summary["authority"] is False
    assert summary["completion_claim_allowed"] is False
    assert summary["fresh_process_verify"] == "passed"
    assert summary["original_pointer_sha256"] != summary["relocated_pointer_sha256"]

    dest = world["dest"]
    receipt_path = dest / "preparation-receipt.json"
    assert receipt_path.is_file()
    raw = receipt_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    receipt = json.loads(raw.decode("utf-8"))
    assert receipt["live_source_mutated"] is False
    assert receipt["migration_executed"] is False
    assert receipt["authority"] is False
    assert receipt["completion_claim_allowed"] is False

    env = receipt["proposed_environment"]
    assert Path(env["XINAO_SKILL_STATE_ROOT"]) == dest / "isolated-state"
    assert Path(env["XINAO_RESEARCHER_RUN_ROOT"]) == dest / "researcher-runs"
    assert Path(env["XINAO_INSTALLED_SKILL_ROOT"]) == dest / "installed-skill"
    sealed_candidate = dest / "candidate-source"
    assert Path(env["XINAO_MIGRATION_SOURCE_ROOT"]) == sealed_candidate
    assert Path(receipt["destination"]["candidate_source_root"]) == sealed_candidate
    assert sealed_candidate.is_dir()
    assert (sealed_candidate / "docker" / "xinao-researcher" / "Dockerfile").read_bytes() == world[
        "candidate_dockerfile_bytes"
    ]
    assert (sealed_candidate / "skills" / "xinao" / "SKILL.md").is_file()

    # Legacy provenance sealed outside skill renderings.
    active_prov = Path(receipt["destination"]["active_legacy_provenance_root"])
    assert active_prov == dest / "evidence" / "legacy-provenance" / "active"
    assert (active_prov / "docker" / "xinao-researcher" / "Dockerfile").read_bytes() == world[
        "legacy_active_dockerfile_bytes"
    ]
    assert world["legacy_active_dockerfile_bytes"] != world["candidate_dockerfile_bytes"]

    relocated_pointer = Path(receipt["destination"]["pointer_path"])
    pointer = json.loads(relocated_pointer.read_text(encoding="utf-8"))
    assert Path(pointer["release_manifest_path"]) == Path(
        receipt["pointer_relocation"]["relocated_release_manifest_path"]
    )
    assert Path(pointer["previous_release_manifest_path"]) == Path(
        receipt["pointer_relocation"]["relocated_previous_release_manifest_path"]
    )
    assert pointer["release_manifest_path"] != str(world["active_path"])
    assert pointer["previous_release_manifest_path"] != str(world["previous_path"])
    assert (
        _sha256_file(relocated_pointer) == receipt["pointer_relocation"]["relocated_pointer_sha256"]
    )
    assert (
        _sha256_file(Path(receipt["destination"]["original_pointer_path"]))
        == receipt["pointer_relocation"]["original_pointer_sha256"]
    )

    assert (
        Path(receipt["destination"]["active_manifest_path"]).read_bytes() == world["active_bytes"]
    )
    assert (
        Path(receipt["destination"]["previous_manifest_path"]).read_bytes()
        == world["previous_bytes"]
    )

    active_staged = Path(receipt["destination"]["active_rendering_root"]) / "SKILL.md"
    previous_staged = Path(receipt["destination"]["previous_rendering_root"]) / "SKILL.md"
    assert active_staged.read_bytes() == world["active_skill_md"]
    assert previous_staged.read_bytes() == world["previous_skill_md"]
    assert b"\r\n" in active_staged.read_bytes()
    assert b"\r\n" not in previous_staged.read_bytes()

    for rel_id, manifest_path in (
        (world["active_id"], Path(receipt["destination"]["active_manifest_path"])),
        (world["previous_id"], Path(receipt["destination"]["previous_manifest_path"])),
    ):
        names = sorted(p.name for p in manifest_path.parent.iterdir())
        assert names == ["release.json"]

    inv = receipt["inventories"]
    for key in (
        "installed_skill",
        "active_rendering",
        "previous_rendering",
        "candidate_source",
        "active_legacy_provenance",
        "previous_legacy_provenance",
    ):
        assert key in inv
        assert isinstance(inv[key], list)
        assert len(inv[key]) >= 1

    _assert_live_unchanged(world)

    verified = _run_helper(_verify_args(world))
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verify_summary = json.loads(verified.stdout.strip().splitlines()[-1])
    assert verify_summary["status"] == "VERIFIED"
    assert verify_summary["completion_claim_allowed"] is False


def test_bad_pointer_hash_fails_closed(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    pointer = json.loads(world["pointer_path"].read_text(encoding="utf-8"))
    pointer["release_manifest_sha256"] = "a" * 64
    _write_json(world["pointer_path"], pointer)
    world["pointer_bytes"] = world["pointer_path"].read_bytes()

    completed = _run_helper(_prepare_args(world))
    _assert_fail_code(completed, "RELEASE_MANIFEST_IDENTITY_MISMATCH")
    assert not world["dest"].exists()
    _assert_live_unchanged(world)


def test_impure_release_fails_closed(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    extra = world["active_path"].parent / "extra.txt"
    extra.write_text("impure\n", encoding="utf-8")

    completed = _run_helper(_prepare_args(world))
    _assert_fail_code(completed, "V1_RELEASE_DIRECTORY_NOT_PURE")
    assert not world["dest"].exists()


def test_rendering_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    skill_md = world["active_rendering"] / "SKILL.md"
    skill_md.write_bytes(skill_md.read_bytes() + b"\n# tamper\r\n")

    completed = _run_helper(_prepare_args(world))
    _assert_fail_code(completed, "MIGRATION_SOURCE_RENDERING_HASH_MISMATCH")
    assert not world["dest"].exists()


def test_destination_exists_fails_closed(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    world["dest"].mkdir(parents=True)
    (world["dest"] / "preexisting.txt").write_text("nope\n", encoding="utf-8")

    completed = _run_helper(_prepare_args(world))
    _assert_fail_code(completed, "DESTINATION_EXISTS")
    assert (world["dest"] / "preexisting.txt").is_file()


def test_destination_escape_from_approved_base_fails(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    outside = tmp_path / "outside" / "escape-cone"
    outside.parent.mkdir(parents=True, exist_ok=True)

    completed = _run_helper(_prepare_args(world, dest=outside))
    _assert_fail_code(completed, "DESTINATION_NOT_UNDER_APPROVED_BASE")
    assert not outside.exists()


def test_extra_file_after_seal_fails_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout

    extra = world["dest"] / "extra-after-seal.txt"
    extra.write_text("drift\n", encoding="utf-8")

    verified = _run_helper(_verify_args(world))
    blob = _combined_output(verified)
    assert verified.returncode != 0
    assert (
        "PROOF_EXTRA_FILE" in blob
        or "PROOF_INVENTORY_COUNT_MISMATCH" in blob
        or "PROOF_TREE_SHA_MISMATCH" in blob
    )


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlink_in_rendering_fails_where_supported(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    target = world["active_rendering"] / "SKILL.md"
    link = world["active_rendering"] / "scripts" / "linked.py"
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink not permitted: {exc}")

    completed = _run_helper(_prepare_args(world))
    blob = _combined_output(completed).lower()
    assert completed.returncode != 0
    assert "reparse" in blob or "skill_bundle_source_invalid" in blob


def test_hardlink_in_rendering_fails(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    src = world["active_rendering"] / "SKILL.md"
    dst = world["active_rendering"] / "references" / "hardlinked-skill.md"
    try:
        os.link(src, dst)
    except OSError as exc:
        pytest.skip(f"hardlink not permitted: {exc}")

    completed = _run_helper(_prepare_args(world))
    blob = _combined_output(completed).lower()
    assert completed.returncode != 0
    assert (
        "hardlink" in blob
        or "nlink" in blob
        or "ambiguity" in blob
        or "file_identity_invalid" in blob
    )


def test_receipt_non_claims_and_inventory_contract(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    completed = _run_helper(_prepare_args(world))
    assert completed.returncode == 0, completed.stderr + completed.stdout
    receipt = json.loads((world["dest"] / "preparation-receipt.json").read_text(encoding="utf-8"))
    for key in (
        "live_source_mutated",
        "migration_executed",
        "authority",
        "completion_claim_allowed",
    ):
        assert receipt[key] is False
    assert "pointer_relocation" in receipt
    assert set(receipt["pointer_relocation"]["keys_relocated"]) == {
        "release_manifest_path",
        "previous_release_manifest_path",
    }
    assert isinstance(receipt["files"], list)
    assert receipt["files_count"] == len(receipt["files"])
    assert receipt["receipt_relative_path"] == "preparation-receipt.json"
    assert all(row["relative_path"] != "preparation-receipt.json" for row in receipt["files"])
    assert all("sha256" in row and "relative_path" in row for row in receipt["files"])
    rels = [row["relative_path"] for row in receipt["files"]]
    assert rels == sorted(rels)
    assert "receipt_content_sha256" in receipt
    assert len(receipt["receipt_content_sha256"]) == 64
    assert "inventories" in receipt
    assert "candidate_source" in receipt["inventories"]
    assert "active_legacy_provenance" in receipt["inventories"]


def test_candidate_mutation_after_prepare_fails_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout

    # Mutate caller-side candidate only — sealed clone must keep VerifyOnly green if truly isolated.
    caller_docker = world["candidate"] / "docker" / "xinao-researcher" / "Dockerfile"
    caller_docker.write_text("FROM mutated-caller\n", encoding="utf-8")
    skill = world["candidate"] / "skills" / "xinao" / "SKILL.md"
    skill.write_text("# mutated caller skill\n", encoding="utf-8")

    still_ok = _run_helper(_verify_args(world))
    assert still_ok.returncode == 0, still_ok.stderr + still_ok.stdout

    # Mutate sealed candidate inside cone — must fail closed.
    sealed = world["dest"] / "candidate-source" / "docker" / "xinao-researcher" / "Dockerfile"
    sealed.write_text("FROM mutated-sealed\n", encoding="utf-8")
    verified = _run_helper(_verify_args(world))
    blob = _combined_output(verified)
    assert verified.returncode != 0
    assert (
        "CANDIDATE_SOURCE_DRIFT" in blob
        or "CANDIDATE_SOURCE_TREE_DRIFT" in blob
        or "PROOF_FILE_DRIFT" in blob
        or "PROOF_TREE_SHA_MISMATCH" in blob
    )


def test_candidate_dockerfile_entrypoint_drift_fails_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout

    entry = world["dest"] / "candidate-source" / "docker" / "xinao-researcher" / "entrypoint.py"
    entry.write_text("print('drifted-entrypoint')\n", encoding="utf-8")
    verified = _run_helper(_verify_args(world))
    _assert_fail_code(verified, "CANDIDATE_SOURCE")


def test_legacy_dockerfile_entrypoint_mismatch_fails_prepare(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    # Break active legacy Dockerfile vs release skill_hashes.dockerfile_sha256.
    docker = world["active_legacy_repo"] / "docker" / "xinao-researcher" / "Dockerfile"
    docker.write_text("FROM wrong-legacy-bytes\n", encoding="utf-8")

    completed = _run_helper(_prepare_args(world))
    _assert_fail_code(completed, "LEGACY_DOCKERFILE_HASH_MISMATCH")
    assert not world["dest"].exists()


def test_legacy_entrypoint_mismatch_fails_prepare(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    entry = world["previous_legacy_repo"] / "docker" / "xinao-researcher" / "entrypoint.py"
    entry.write_text("print('wrong-previous-entrypoint')\n", encoding="utf-8")

    completed = _run_helper(_prepare_args(world))
    _assert_fail_code(completed, "LEGACY_ENTRYPOINT_HASH_MISMATCH")
    assert not world["dest"].exists()


def test_receipt_inventories_key_deletion_fails_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout
    receipt_path = world["dest"] / "preparation-receipt.json"

    def drop_inventories(receipt: dict[str, Any]) -> None:
        del receipt["inventories"]

    _rewrite_receipt(receipt_path, drop_inventories)
    verified = _run_helper(_verify_args(world))
    _assert_fail_code(verified, "RECEIPT_SCHEMA_INVALID")


def test_receipt_unknown_key_fails_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout
    receipt_path = world["dest"] / "preparation-receipt.json"

    def add_unknown(receipt: dict[str, Any]) -> None:
        receipt["unexpected_top_level"] = True

    _rewrite_receipt(receipt_path, add_unknown)
    verified = _run_helper(_verify_args(world))
    _assert_fail_code(verified, "RECEIPT_SCHEMA_INVALID")


def test_rendering_source_toctou_fails_prepare(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    completed = _run_helper(
        _prepare_args(world),
        env={"XINAO_TEST_MUTATE_RENDERING_AFTER_PREFLIGHT": "1"},
    )
    blob = _combined_output(completed)
    assert completed.returncode != 0
    assert (
        "RENDERING_COPY_FAILED" in blob
        or "LIVE_SOURCE_MUTATED" in blob
        or "preflight tree sha mismatch" in blob
        or "preflight-bind" in blob
    )
    # Owned cone cleaned or absent; never leave false VERIFIED.
    if world["dest"].exists():
        assert not (world["dest"] / "preparation-receipt.json").is_file()


def test_forced_hardlink_probe_failure(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    completed = _run_helper(
        _prepare_args(world),
        env={"XINAO_TEST_FORCE_HARDLINK_PROBE_FAILURE": "1"},
    )
    _assert_fail_code(completed, "HARDLINK_PROBE_FAILED")
    assert not world["dest"].exists() or not (world["dest"] / "preparation-receipt.json").exists()


def test_early_junction_rejection(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("junction probe is Windows-specific")
    world = _build_world(tmp_path)
    escape = tmp_path / "escape_target"
    escape.mkdir(parents=True, exist_ok=True)
    (escape / "sentinel.txt").write_text("escape\n", encoding="utf-8")
    junction = world["approved_base"] / "junc"
    # mklink /J requires cmd
    link = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(escape)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if link.returncode != 0:
        pytest.skip(f"mklink /J failed: {link.stdout}{link.stderr}")

    dest = junction / "proof-under-junc"
    completed = _run_helper(_prepare_args(world, dest=dest))
    _assert_fail_code(completed, "DESTINATION_REPARSE_FORBIDDEN")
    assert not (escape / "preparation-receipt.json").exists()
    assert (
        list(escape.iterdir()) == [escape / "sentinel.txt"] or (escape / "sentinel.txt").is_file()
    )


def test_destination_path_topology_tamper_fails_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout
    receipt_path = world["dest"] / "preparation-receipt.json"

    def tamper_topology(receipt: dict[str, Any]) -> None:
        # Point migration source outside sealed cone topology.
        receipt["proposed_environment"]["XINAO_MIGRATION_SOURCE_ROOT"] = str(world["candidate"])
        receipt["destination"]["candidate_source_root"] = str(world["candidate"])

    _rewrite_receipt(receipt_path, tamper_topology)
    verified = _run_helper(_verify_args(world))
    blob = _combined_output(verified)
    assert verified.returncode != 0
    assert "PROOF_PATH_TOPOLOGY_INVALID" in blob or "RECEIPT_SCHEMA_INVALID" in blob


def test_cleanup_ownership_preserves_caller_and_requires_marker(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    # Pre-existing dest must not be deleted (not owned).
    world["dest"].mkdir(parents=True)
    caller_file = world["dest"] / "caller-owned.txt"
    caller_file.write_text("keep-me\n", encoding="utf-8")
    completed = _run_helper(_prepare_args(world))
    _assert_fail_code(completed, "DESTINATION_EXISTS")
    assert caller_file.is_file()
    assert caller_file.read_text(encoding="utf-8") == "keep-me\n"

    # Failure before ownership (impure release) must not create/delete unrelated paths.
    shutil.rmtree(world["dest"], ignore_errors=True)
    sibling = world["approved_base"] / "sibling-unrelated"
    sibling.mkdir(parents=True, exist_ok=True)
    sibling_file = sibling / "keep.txt"
    sibling_file.write_text("sibling\n", encoding="utf-8")
    extra = world["active_path"].parent / "extra.txt"
    extra.write_text("impure\n", encoding="utf-8")
    completed2 = _run_helper(_prepare_args(world))
    _assert_fail_code(completed2, "V1_RELEASE_DIRECTORY_NOT_PURE")
    assert sibling_file.is_file()
    assert not world["dest"].exists()


def test_live_source_unchanged_after_success(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    completed = _run_helper(_prepare_args(world))
    assert completed.returncode == 0, completed.stderr + completed.stdout
    _assert_live_unchanged(world)


def _find_git() -> str:
    path = shutil.which("git")
    if not path:
        pytest.skip("git is unavailable")
    return path


def _force_rmtree(path: Path) -> None:
    """Remove trees that contain read-only Git object files (Windows)."""
    if not path.exists():
        return

    def _onexc(func, p, _exc_info):  # noqa: ANN001
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            raise

    # Python 3.12 prefers onexc; keep onerror for broader compatibility.
    try:
        shutil.rmtree(path, onexc=_onexc)
    except TypeError:
        shutil.rmtree(path, onerror=_onexc)


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    git = _find_git()
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        [git, "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )


def test_prepared_candidate_source_satisfies_build_release_git_preconditions(
    tmp_path: Path,
) -> None:
    world = _build_world(tmp_path)
    completed = _run_helper(_prepare_args(world))
    assert completed.returncode == 0, completed.stderr + completed.stdout

    sealed = world["dest"] / "candidate-source"
    receipt = json.loads((world["dest"] / "preparation-receipt.json").read_text(encoding="utf-8"))
    identity = receipt["candidate_source_git_identity"]
    assert identity["schema_version"] == "xinao.isolated_legacy_migration_candidate_git_identity.v1"
    assert identity["repository_kind"] == "local_regular_directory"
    assert identity["git_dir_relative_path"] == ".git"
    assert identity["external_gitdir_absent"] is True
    assert identity["alternates_absent"] is True
    assert identity["status_porcelain"] == ""
    assert identity["branch"] == "proof"
    assert (sealed / ".git").is_dir()
    assert not (sealed / ".git").is_symlink()
    assert not (sealed / ".git").is_file()

    # Actual consumer preconditions used by build_release().
    head = _run_git(sealed, "rev-parse", "HEAD")
    tree = _run_git(sealed, "rev-parse", "HEAD^{tree}")
    status = _run_git(sealed, "status", "--porcelain")
    assert head.returncode == 0, head.stderr
    assert tree.returncode == 0, tree.stderr
    assert status.returncode == 0, status.stderr
    assert head.stdout.strip() == identity["head_commit"]
    assert tree.stdout.strip() == identity["head_tree"]
    assert status.stdout.strip() == ""
    assert len(identity["head_commit"]) >= 40
    assert len(identity["head_tree"]) >= 40

    tracked = [row["relative_path"] for row in identity["tracked_files"]]
    product = sorted(world["candidate_snapshot"].keys())
    assert tracked == product
    for row in identity["tracked_files"]:
        abs_path = sealed / Path(row["relative_path"])
        assert abs_path.is_file()
        assert _sha256_file(abs_path) == row["content_sha256"]
        assert abs_path.stat().st_size == row["size"]
        assert world["candidate_snapshot"][row["relative_path"]] == abs_path.read_bytes()

    # XINAO_MIGRATION_SOURCE_ROOT remains the sealed clone (not caller worktree).
    env = receipt["proposed_environment"]
    assert Path(env["XINAO_MIGRATION_SOURCE_ROOT"]) == sealed
    assert Path(env["XINAO_MIGRATION_SOURCE_ROOT"]) != world["candidate"]

    verified = _run_helper(_verify_args(world))
    assert verified.returncode == 0, verified.stderr + verified.stdout


def test_external_gitdir_pointer_fails_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout

    sealed = world["dest"] / "candidate-source"
    git_dir = sealed / ".git"
    _force_rmtree(git_dir)
    # External gitdir pointer (forbidden).
    outside = tmp_path / "outside-gitdir"
    outside.mkdir()
    git_dir.write_text(f"gitdir: {outside}\n", encoding="utf-8")
    assert git_dir.is_file()

    verified = _run_helper(_verify_args(world))
    blob = _combined_output(verified)
    assert verified.returncode != 0
    assert "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT" in blob or "external .git pointer" in blob.lower()


def test_alternates_fail_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout

    alternates = world["dest"] / "candidate-source" / ".git" / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(str(tmp_path / "object-store") + "\n", encoding="utf-8")

    verified = _run_helper(_verify_args(world))
    _assert_fail_code(verified, "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT")


def test_dirty_and_untracked_fail_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout

    sealed = world["dest"] / "candidate-source"
    # Dirty tracked product file.
    docker = sealed / "docker" / "xinao-researcher" / "Dockerfile"
    docker.write_bytes(docker.read_bytes() + b"\n# dirty\n")
    dirty = _run_helper(_verify_args(world))
    blob = _combined_output(dirty)
    assert dirty.returncode != 0
    assert (
        "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT" in blob
        or "CANDIDATE_SOURCE_DRIFT" in blob
        or "CANDIDATE_SOURCE_TREE_DRIFT" in blob
        or "PROOF_FILE_DRIFT" in blob
    )

    # Restore product bytes for untracked case via re-prepare in fresh dest.
    world2 = _build_world(tmp_path / "untracked-case")
    prepared2 = _run_helper(_prepare_args(world2))
    assert prepared2.returncode == 0, prepared2.stderr + prepared2.stdout
    sealed2 = world2["dest"] / "candidate-source"
    untracked = sealed2 / "skills" / "xinao" / "untracked-extra.txt"
    untracked.write_text("untracked\n", encoding="utf-8")
    verified = _run_helper(_verify_args(world2))
    blob2 = _combined_output(verified)
    assert verified.returncode != 0
    assert (
        "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT" in blob2
        or "CANDIDATE_SOURCE_DRIFT" in blob2
        or "PROOF_EXTRA_FILE" in blob2
        or "PROOF_INVENTORY_COUNT_MISMATCH" in blob2
        or "PROOF_TREE_SHA_MISMATCH" in blob2
    )


def test_tracked_set_and_head_tree_drift_fail_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout
    sealed = world["dest"] / "candidate-source"

    extra = sealed / "skills" / "xinao" / "extra-tracked.txt"
    extra.write_text("extra-tracked\n", encoding="utf-8")
    add = _run_git(
        sealed,
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.hooksPath=.git/xinao-empty-hooks",
        "add",
        "--",
        "skills/xinao/extra-tracked.txt",
    )
    assert add.returncode == 0, add.stderr
    commit = _run_git(
        sealed,
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.hooksPath=.git/xinao-empty-hooks",
        "commit",
        "--no-verify",
        "-m",
        "drift commit",
    )
    assert commit.returncode == 0, commit.stderr

    verified = _run_helper(_verify_args(world))
    blob = _combined_output(verified)
    assert verified.returncode != 0
    assert (
        "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT" in blob
        or "CANDIDATE_SOURCE_DRIFT" in blob
        or "PROOF_EXTRA_FILE" in blob
        or "PROOF_TREE_SHA_MISMATCH" in blob
    )


def test_blob_and_config_hooks_drift_fail_verify(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout
    sealed = world["dest"] / "candidate-source"

    # Config drift.
    cfg = _run_git(sealed, "config", "--local", "core.autocrlf", "true")
    assert cfg.returncode == 0, cfg.stderr
    verified_cfg = _run_helper(_verify_args(world))
    _assert_fail_code(verified_cfg, "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT")

    # Restore autocrlf then break hooksPath.
    world_h = _build_world(tmp_path / "hooks-case")
    prepared_h = _run_helper(_prepare_args(world_h))
    assert prepared_h.returncode == 0, prepared_h.stderr + prepared_h.stdout
    sealed_h = world_h["dest"] / "candidate-source"
    hooks = _run_git(sealed_h, "config", "--local", "core.hooksPath", ".git/hooks")
    assert hooks.returncode == 0, hooks.stderr
    verified_h = _run_helper(_verify_args(world_h))
    _assert_fail_code(verified_h, "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT")

    # HEAD rewrite without product inventory change attempt: update-ref to empty tree commit is hard;
    # mutate receipt head_commit instead (schema-bound revalidation).
    world_r = _build_world(tmp_path / "receipt-head-case")
    prepared_r = _run_helper(_prepare_args(world_r))
    assert prepared_r.returncode == 0, prepared_r.stderr + prepared_r.stdout
    receipt_path = world_r["dest"] / "preparation-receipt.json"

    def tamper_head(receipt: dict[str, Any]) -> None:
        receipt["candidate_source_git_identity"]["head_commit"] = "a" * 40
        receipt["candidate_source_git_identity"]["head_tree"] = "b" * 40

    _rewrite_receipt(receipt_path, tamper_head)
    verified_r = _run_helper(_verify_args(world_r))
    _assert_fail_code(verified_r, "CANDIDATE_SOURCE_GIT_IDENTITY_DRIFT")


def test_caller_candidate_mutation_keeps_sealed_git_verify_green(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    prepared = _run_helper(_prepare_args(world))
    assert prepared.returncode == 0, prepared.stderr + prepared.stdout

    sealed = world["dest"] / "candidate-source"
    before_head = _run_git(sealed, "rev-parse", "HEAD").stdout.strip()
    before_tree = _run_git(sealed, "rev-parse", "HEAD^{tree}").stdout.strip()

    # Mutate only the caller-side candidate root; sealed clone + git identity must remain valid.
    caller_docker = world["candidate"] / "docker" / "xinao-researcher" / "Dockerfile"
    caller_docker.write_text("FROM mutated-caller-again\n", encoding="utf-8")
    (world["candidate"] / "skills" / "xinao" / "SKILL.md").write_text(
        "# caller mutated\n", encoding="utf-8"
    )

    verified = _run_helper(_verify_args(world))
    assert verified.returncode == 0, verified.stderr + verified.stdout
    assert _run_git(sealed, "rev-parse", "HEAD").stdout.strip() == before_head
    assert _run_git(sealed, "rev-parse", "HEAD^{tree}").stdout.strip() == before_tree
    assert _run_git(sealed, "status", "--porcelain").stdout.strip() == ""
    assert (sealed / "docker" / "xinao-researcher" / "Dockerfile").read_bytes() == world[
        "candidate_dockerfile_bytes"
    ]
