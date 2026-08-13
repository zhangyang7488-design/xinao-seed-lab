from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "Build-XinaoNativeColdRetirementPack.ps1"
PINNED_PWSH = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4\pwsh.exe")


def _pwsh() -> str | None:
    on_path = shutil.which("pwsh")
    if on_path:
        return on_path
    if PINNED_PWSH.is_file():
        return str(PINNED_PWSH)
    return None


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def synthetic_old_x(tmp_path: Path) -> dict[str, object]:
    if shutil.which("git") is None:
        pytest.skip("git is required")

    repo = tmp_path / "synthetic-old-x"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.name", "Synthetic Retirement Test")
    _git(repo, "config", "user.email", "retirement@example.invalid")

    _write(
        repo / ".gitignore",
        ".pytest_cache/\n.ruff_cache/\n__pycache__/\n",
    )
    _write(repo / "AGENTS.md", "base agents\n")
    _write(repo / "tracked.txt", "base tracked\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "base")
    base_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "--quiet", "-b", "discarded-candidate")
    _write(repo / "unreachable-only.txt", "unique unreachable bytes\n")
    _git(repo, "add", "unreachable-only.txt")
    _git(repo, "commit", "--quiet", "-m", "discarded candidate")
    unreachable_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "--quiet", "main")
    _git(repo, "branch", "-D", "discarded-candidate")
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    fsck = _git(repo, "fsck", "--full", "--unreachable").stdout
    assert unreachable_commit in fsck

    _write(repo / "tracked.txt", "stashed tracked bytes\n")
    _write(repo / "stash-untracked.txt", "stashed untracked bytes\n")
    _git(repo, "stash", "push", "--include-untracked", "-m", "synthetic stash")
    linked_worktrees = [tmp_path / "linked-worktree-a", tmp_path / "linked-worktree-b"]
    for linked_worktree in linked_worktrees:
        _git(repo, "worktree", "add", "--quiet", "--detach", str(linked_worktree), "HEAD")
    _write(repo / "AGENTS.md", "base agents\ndirty live correction\n")

    _write(repo / ".pytest_cache" / "v" / "cache" / "nodeids", "[]\n")
    _write(repo / ".ruff_cache" / "content", "derived\n")
    _write(repo / "pkg" / "__pycache__" / "mod.cpython-313.pyc", "derived\n")

    artifact_store = tmp_path / "artifact-store"
    cas_id = "ab" * 32
    cas_path = artifact_store / "objects" / "sha256" / cas_id[:2] / f"{cas_id}.json"
    _write(cas_path, '{"payload":"unique artifact"}\n')
    event = {
        "schema_version": "xinao.artifact-journal-event.v1",
        "payload": {
            "artifact_id": "sha256:" + ("cd" * 32),
            "cas_sha256": cas_id,
            "kind": "synthetic",
        },
    }
    _write(
        artifact_store / "journals" / "artifacts" / "registrations.jsonl",
        json.dumps(event, separators=(",", ":")) + "\n",
    )

    live_root = tmp_path / "live-consumers"
    cold_root = tmp_path / "cold-references"
    _write(live_root / "launcher.ps1", f"$repo = '{repo}'\n")
    _write(live_root / "sessions" / "rollout.json", f'{{"repo":"{repo}"}}\n')
    _write(cold_root / "pointer.md", f"Cold donor: `{repo}`\n")

    legacy_bundle = tmp_path / "legacy.bundle"
    _git(repo, "bundle", "create", str(legacy_bundle), "--all")
    missing_handoff = tmp_path / "CURRENT_LOCAL_WORLD_HANDOFF_missing.zip"

    return {
        "repo": repo,
        "artifact_store": artifact_store,
        "cas_id": cas_id,
        "cas_path": cas_path,
        "live_root": live_root,
        "cold_root": cold_root,
        "legacy_bundle": legacy_bundle,
        "missing_handoff": missing_handoff,
        "linked_worktrees": linked_worktrees,
        "unreachable_commit": unreachable_commit,
        "base_head": base_head,
    }


def _run_builder(
    fixture: dict[str, object], staging: Path
) -> subprocess.CompletedProcess[str]:
    powershell = _pwsh()
    if powershell is None:
        pytest.skip("PowerShell 7.4+ is required")
    return subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(SCRIPT),
            "-SourceRepository",
            str(fixture["repo"]),
            "-StagingPath",
            str(staging),
            "-ArtifactStorePath",
            str(fixture["artifact_store"]),
            "-LiveConsumerRoot",
            str(fixture["live_root"]),
            "-ColdReferenceRoot",
            str(fixture["cold_root"]),
            "-DesktopHandoffPath",
            str(fixture["missing_handoff"]),
            "-LegacyBundlePath",
            str(fixture["legacy_bundle"]),
            "-ExpectedLinkedWorktreeCount",
            "2",
            "-MinimumStashCount",
            "1",
            "-MinimumUnreachableObjectCount",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )


def test_builder_preserves_unreachable_dirty_stash_and_unique_state(
    synthetic_old_x: dict[str, object], tmp_path: Path
) -> None:
    repo = synthetic_old_x["repo"]
    assert isinstance(repo, Path)
    status_before = _git(repo, "status", "--porcelain=v2", "--untracked-files=all").stdout
    refs_before = _git(
        repo,
        "for-each-ref",
        "--format=%(refname)%09%(objectname)%09%(objecttype)",
    ).stdout
    fsck_before = _git(repo, "fsck", "--full", "--unreachable").stdout

    staging = tmp_path / "empty-staging"
    staging.mkdir()
    completed = _run_builder(synthetic_old_x, staging)
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

    assert not (staging / "_INCOMPLETE.json").exists()
    assert (staging / "BUILD_COMPLETE.json").is_file()
    manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads(
        (staging / "evidence" / "retirement-evidence.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "payload_verified"
    assert manifest["source_deleted"] is False
    assert manifest["source_mutated"] is False
    assert manifest["payload_policy"]["copy_first"] is True
    assert manifest["payload_policy"]["auth_session_browser_tmp_secret_copied"] is False
    assert manifest["fresh_readback"]["copied_git_matches_source_snapshot"] is True

    unreachable_commit = str(synthetic_old_x["unreachable_commit"])
    unreachable_ids = {
        item["object_id"] for item in evidence["git"]["unreachable_objects"]
    }
    assert unreachable_commit in unreachable_ids
    copied_git = staging / "payload" / "git-exact" / ".git"
    copied_object = subprocess.run(
        ["git", "--git-dir", str(copied_git), "cat-file", "-e", unreachable_commit],
        check=False,
        capture_output=True,
    )
    assert copied_object.returncode == 0

    bundle = staging / "payload" / "git-bundle" / "xinao-native-research.bundle"
    verify = subprocess.run(
        ["git", "--git-dir", str(copied_git), "bundle", "verify", str(bundle)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert evidence["git"]["named_ref_bundle"]["verified"] is True

    assert evidence["dirty_agents"]["dirty"] is True
    current_agents = staging / evidence["dirty_agents"]["current_relative_path"]
    base_agents = staging / evidence["dirty_agents"]["base_relative_path"]
    agents_diff = staging / evidence["dirty_agents"]["diff_relative_path"]
    assert current_agents.read_bytes() == (repo / "AGENTS.md").read_bytes()
    assert current_agents.read_bytes() != base_agents.read_bytes()
    assert b"dirty live correction" in agents_diff.read_bytes()

    assert len(evidence["stash"]) == 1
    stash_inventory = "\n".join(evidence["stash"][0]["name_status"])
    assert "tracked.txt" in stash_inventory
    assert "stash-untracked.txt" in stash_inventory
    stash_patch = staging / evidence["stash"][0]["patch_relative_path"]
    assert stash_patch.is_file() and stash_patch.stat().st_size > 0

    cas_id = str(synthetic_old_x["cas_id"])
    copied_cas = (
        staging
        / "payload"
        / "artifact-store"
        / "objects"
        / "sha256"
        / cas_id[:2]
        / f"{cas_id}.json"
    )
    assert copied_cas.read_bytes() == Path(synthetic_old_x["cas_path"]).read_bytes()
    assert evidence["artifact_store"]["cas_ids"] == [cas_id]
    assert evidence["artifact_store"]["lock_files_copied"] is False

    classifications = {
        (item["classification"], Path(item["path"]).name)
        for item in evidence["consumers"]["textual_matches"]
    }
    assert ("live_or_latent_consumer", "launcher.ps1") in classifications
    assert ("cold_textual_reference", "pointer.md") in classifications
    assert all(Path(item["path"]).name != "rollout.json" for item in evidence["consumers"]["textual_matches"])
    assert evidence["consumers"]["excluded_counts"]["prohibited_path"] >= 1
    assert evidence["consumers"]["raw_consumer_bytes_copied"] is False

    cache_classes = {item["classification"] for item in evidence["cache_exclusions"]}
    assert cache_classes == {".pytest_cache", ".ruff_cache", "__pycache__"}
    assert evidence["desktop_handoff"]["status"] == "missing"
    assert evidence["legacy_bundles"][0]["status"] == "present_verified"
    assert evidence["legacy_bundles"][0]["lists_current_head"] is True
    assert evidence["legacy_bundles"][0]["covers_current_named_ref_tips"] is True
    linked_paths = {Path(item["path"]) for item in evidence["linked_worktrees"]}
    assert linked_paths == set(synthetic_old_x["linked_worktrees"])
    assert all(item["clean"] is True for item in evidence["linked_worktrees"])
    copied_worktree_admin = copied_git / "worktrees"
    assert copied_worktree_admin.is_dir()
    assert len([path for path in copied_worktree_admin.iterdir() if path.is_dir()]) == 2

    assert _git(repo, "status", "--porcelain=v2", "--untracked-files=all").stdout == status_before
    assert (
        _git(
            repo,
            "for-each-ref",
            "--format=%(refname)%09%(objectname)%09%(objecttype)",
        ).stdout
        == refs_before
    )
    assert _git(repo, "fsck", "--full", "--unreachable").stdout == fsck_before


def test_builder_rejects_nonempty_staging_without_success_receipt(
    synthetic_old_x: dict[str, object], tmp_path: Path
) -> None:
    staging = tmp_path / "nonempty-staging"
    staging.mkdir()
    _write(staging / "belongs-to-caller.txt", "do not overwrite\n")

    completed = _run_builder(synthetic_old_x, staging)
    assert completed.returncode != 0
    assert "RETIREMENT_PACK_STAGING_NOT_EMPTY" in completed.stderr
    assert not (staging / "manifest.json").exists()
    assert not (staging / "BUILD_COMPLETE.json").exists()
    assert (staging / "belongs-to-caller.txt").read_text(encoding="utf-8") == "do not overwrite\n"


def test_builder_rejects_uncaptured_untracked_file_fail_closed(
    synthetic_old_x: dict[str, object], tmp_path: Path
) -> None:
    repo = synthetic_old_x["repo"]
    assert isinstance(repo, Path)
    _write(repo / "unexpected-untracked.txt", "must not be silently omitted\n")
    staging = tmp_path / "untracked-failure-staging"
    staging.mkdir()

    completed = _run_builder(synthetic_old_x, staging)
    assert completed.returncode != 0
    assert "RETIREMENT_PACK_UNTRACKED_NOT_CAPTURED" in completed.stderr
    assert not (staging / "manifest.json").exists()
    assert not (staging / "BUILD_COMPLETE.json").exists()
    failed = json.loads((staging / "_INCOMPLETE.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert (repo / "unexpected-untracked.txt").read_text(encoding="utf-8") == (
        "must not be silently omitted\n"
    )


def test_builder_rejects_staging_inside_source_before_writing(
    synthetic_old_x: dict[str, object]
) -> None:
    repo = synthetic_old_x["repo"]
    assert isinstance(repo, Path)
    status_before = _git(repo, "status", "--porcelain=v2", "--untracked-files=all").stdout
    staging = repo / "empty-but-inside-source"
    staging.mkdir()

    completed = _run_builder(synthetic_old_x, staging)
    assert completed.returncode != 0
    assert "RETIREMENT_PACK_STAGING_OVERLAPS_SOURCE" in completed.stderr
    assert list(staging.iterdir()) == []
    assert _git(repo, "status", "--porcelain=v2", "--untracked-files=all").stdout == status_before


def test_builder_rejects_sensitive_git_config_before_copying(
    synthetic_old_x: dict[str, object], tmp_path: Path
) -> None:
    repo = synthetic_old_x["repo"]
    assert isinstance(repo, Path)
    _git(
        repo,
        "config",
        "http.https://example.invalid/.extraheader",
        "AUTHORIZATION: bearer synthetic-not-a-real-token",
    )
    staging = tmp_path / "sensitive-config-staging"
    staging.mkdir()

    completed = _run_builder(synthetic_old_x, staging)
    assert completed.returncode != 0
    assert "RETIREMENT_PACK_SENSITIVE_GIT_CONFIG_KEY" in completed.stderr
    assert not (staging / "payload").exists()
    assert not (staging / "manifest.json").exists()
    assert not (staging / "BUILD_COMPLETE.json").exists()
    failed = json.loads((staging / "_INCOMPLETE.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
