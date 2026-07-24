from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from scripts.build_s_runtime_release import (
    _git_blob_oid,
    build_release,
    verify_release,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def test_git_blob_oid_matches_git_hash_object(tmp_path: Path) -> None:
    payload = b"one\r\ntwo\n"
    sample = tmp_path / "sample.txt"
    sample.write_bytes(payload)
    expected = subprocess.run(
        ["git", "hash-object", "--no-filters", str(sample)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    assert _git_blob_oid(payload, "sha1") == expected


def test_release_builder_preserves_blob_bytes_unicode_and_idempotency(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    release_root = tmp_path / "releases"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "release-test@local")
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "core.autocrlf", "true")
    source = repo / "中文目录" / "换行.txt"
    source.parent.mkdir()
    source.write_bytes(b"line-one\nline-two\n")
    (repo / "plain.txt").write_text("plain\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")

    first = build_release(repo, release_root, commit)
    release_dir = Path(first["release_dir"])
    manifest = release_root / f"{commit}.release-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert first["status"] == "VERIFIED"
    assert first["idempotent"] is False
    assert (release_dir / "中文目录" / "换行.txt").read_bytes() == b"line-one\nline-two\n"
    assert payload["file_count"] == 2
    assert (
        payload["archive_sha256"]
        == hashlib.sha256((release_root / f"{commit}.tar").read_bytes()).hexdigest()
    )
    bytes_only = verify_release(release_dir, manifest)
    assert bytes_only["status"] == "VERIFIED_BYTES_ONLY"
    assert bytes_only["git_commit_verified"] is False
    commit_verified = verify_release(release_dir, manifest, git_repo=repo)
    assert commit_verified["status"] == "VERIFIED"
    assert commit_verified["git_commit_verified"] is True

    original_manifest = manifest.read_bytes()
    drifted = json.loads(original_manifest)
    drifted["tree"] = "0" * 40
    manifest.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(ValueError, match="tree does not match"):
        verify_release(release_dir, manifest, git_repo=repo)
    manifest.write_bytes(original_manifest)

    second = build_release(repo, release_root, commit)
    assert second["idempotent"] is True
    assert second["manifest_sha256"] == first["manifest_sha256"]
