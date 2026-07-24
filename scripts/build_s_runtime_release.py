#!/usr/bin/env python3
"""Build and verify one content-addressed S runtime source release.

The release directory is an exact Git tree, not a mutable worktree copy.  A
separate manifest binds every extracted byte to its Git object and SHA-256.
The directory is promoted last, so its presence is the completion marker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "xinao.s_runtime_source_release.v1"
DEFAULT_RELEASE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\s_runtime_releases")


def _run_git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=text,
        timeout=120,
    )
    return completed.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_oid(payload: bytes, object_format: str) -> str:
    if object_format not in {"sha1", "sha256"}:
        raise ValueError(f"unsupported Git object format: {object_format}")
    header = f"blob {len(payload)}\0".encode()
    digest = hashlib.new(object_format)
    digest.update(header)
    digest.update(payload)
    return digest.hexdigest()


def _safe_parts(raw: str) -> tuple[str, ...]:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe release member path: {raw!r}")
    if "\\" in raw:
        raise ValueError(f"release member path is not canonical POSIX: {raw!r}")
    if any(part == "__pycache__" for part in path.parts) or path.suffix.casefold() == ".pyc":
        raise ValueError(f"compiled Python artifact is forbidden in a source release: {raw}")
    return tuple(path.parts)


def _git_tree(repo: Path, commit: str) -> tuple[str, dict[str, dict[str, str]]]:
    object_format = str(_run_git(repo, "rev-parse", "--show-object-format")).strip()
    raw = _run_git(repo, "ls-tree", "-r", "-z", "--full-tree", commit, text=False)
    assert isinstance(raw, bytes)
    entries: dict[str, dict[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        path = raw_path.decode("utf-8")
        _safe_parts(path)
        if object_type != "blob":
            raise ValueError(
                f"non-blob Git entry is unsupported in an S runtime release: {path} ({object_type})"
            )
        entries[path] = {"mode": mode, "git_oid": object_id}
    if not entries:
        raise ValueError("release commit has no files")
    return object_format, entries


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _extract_and_verify(
    archive_path: Path,
    staging_dir: Path,
    *,
    expected: dict[str, dict[str, str]],
    object_format: str,
) -> dict[str, dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    with tarfile.open(archive_path, mode="r:") as archive:
        members = archive.getmembers()
        file_members = [member for member in members if member.isfile()]
        unsupported = [member.name for member in members if not (member.isfile() or member.isdir())]
        if unsupported:
            raise ValueError(f"release archive contains unsupported members: {unsupported}")
        names = {member.name for member in file_members}
        if names != set(expected):
            raise ValueError(
                "release archive file set differs from Git tree: "
                f"missing={sorted(set(expected) - names)}, extra={sorted(names - set(expected))}"
            )
        for member in file_members:
            parts = _safe_parts(member.name)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read release archive member: {member.name}")
            payload = source.read()
            git_oid = _git_blob_oid(payload, object_format)
            if git_oid != expected[member.name]["git_oid"]:
                raise ValueError(f"release bytes differ from Git blob: {member.name}")
            target = staging_dir.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            observed[member.name] = {
                **expected[member.name],
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
    disk_names = {
        path.relative_to(staging_dir).as_posix()
        for path in staging_dir.rglob("*")
        if path.is_file()
    }
    if disk_names != set(expected):
        raise ValueError("extracted release contains untracked or missing files")
    return observed


def verify_release(
    release_dir: Path,
    manifest_path: Path,
    *,
    git_repo: Path | None = None,
) -> dict[str, Any]:
    release_dir = release_dir.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported S runtime release manifest")
    commit = str(manifest.get("commit") or "")
    if release_dir.name != commit:
        raise ValueError("S runtime release directory is not named by its commit")
    canonical_manifest = release_dir.parent / f"{commit}.release-manifest.json"
    if manifest_path != canonical_manifest:
        raise ValueError("S runtime release manifest is not the canonical commit sibling")
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("S runtime release manifest has no file identities")
    observed_names = {
        path.relative_to(release_dir).as_posix()
        for path in release_dir.rglob("*")
        if path.is_file()
    }
    if observed_names != set(expected):
        raise ValueError("S runtime release directory file set drifted")
    for relative, binding in expected.items():
        path = release_dir.joinpath(*_safe_parts(relative))
        if path.stat().st_size != int(binding["bytes"]) or _sha256(path) != binding["sha256"]:
            raise ValueError(f"S runtime release file drifted: {relative}")
        if (
            _git_blob_oid(path.read_bytes(), str(manifest["git_object_format"]))
            != binding["git_oid"]
        ):
            raise ValueError(f"S runtime release Git identity drifted: {relative}")
    git_commit_verified = False
    if git_repo is not None:
        repo = git_repo.resolve(strict=True)
        object_format, git_entries = _git_tree(repo, commit)
        if object_format != manifest.get("git_object_format"):
            raise ValueError("S runtime release Git object format drifted")
        manifest_entries = {
            relative: {
                "mode": str(binding.get("mode") or ""),
                "git_oid": str(binding.get("git_oid") or ""),
            }
            for relative, binding in expected.items()
        }
        if manifest_entries != git_entries:
            raise ValueError("S runtime release manifest differs from the committed Git tree")
        observed_tree = str(_run_git(repo, "rev-parse", f"{commit}^{{tree}}")).strip()
        if observed_tree != manifest.get("tree"):
            raise ValueError("S runtime release tree does not match its Git commit")
        git_commit_verified = True
    return {
        "status": "VERIFIED" if git_commit_verified else "VERIFIED_BYTES_ONLY",
        "commit": commit,
        "tree": manifest["tree"],
        "git_commit_verified": git_commit_verified,
        "release_dir": str(release_dir),
        "manifest_ref": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "file_count": len(expected),
    }


def build_release(repo: Path, release_root: Path, revision: str) -> dict[str, Any]:
    repo = repo.resolve()
    release_root = release_root.resolve()
    commit = str(_run_git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")).strip()
    if len(commit) != 40:
        raise ValueError("S runtime release currently requires one 40-character commit")
    final_dir = release_root / commit
    final_tar = release_root / f"{commit}.tar"
    final_manifest = release_root / f"{commit}.release-manifest.json"
    if final_dir.exists():
        if not final_tar.is_file() or not final_manifest.is_file():
            raise ValueError("existing release is incomplete; refusing implicit repair")
        result = verify_release(final_dir, final_manifest, git_repo=repo)
        if (
            _sha256(final_tar)
            != json.loads(final_manifest.read_text(encoding="utf-8"))["archive_sha256"]
        ):
            raise ValueError("existing release archive drifted")
        result["idempotent"] = True
        return result

    release_root.mkdir(parents=True, exist_ok=True)
    identity = uuid.uuid4().hex
    staging_dir = release_root / f".staging-{commit}-{identity}"
    staging_tar = release_root / f".staging-{commit}-{identity}.tar"
    staging_manifest = release_root / f".staging-{commit}-{identity}.manifest.json"
    if any(path.exists() for path in (staging_dir, staging_tar, staging_manifest)):
        raise ValueError("release staging identity unexpectedly exists")
    staging_dir.mkdir()
    try:
        subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "archive",
                "--format=tar",
                f"--output={staging_tar}",
                commit,
            ],
            cwd=repo,
            check=True,
            timeout=120,
        )
        object_format, expected = _git_tree(repo, commit)
        files = _extract_and_verify(
            staging_tar,
            staging_dir,
            expected=expected,
            object_format=object_format,
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "VERIFIED_BEFORE_PROMOTION",
            "commit": commit,
            "tree": str(_run_git(repo, "rev-parse", f"{commit}^{{tree}}")).strip(),
            "git_object_format": object_format,
            "archive_sha256": _sha256(staging_tar),
            "file_count": len(files),
            "files": files,
            "generated_at": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "authority": False,
        }
        _write_json(staging_manifest, manifest)
        os.replace(staging_tar, final_tar)
        os.replace(staging_manifest, final_manifest)
        os.replace(staging_dir, final_dir)
    except Exception:
        if staging_tar.exists():
            staging_tar.unlink()
        if staging_manifest.exists():
            staging_manifest.unlink()
        if staging_dir.exists():
            import shutil

            shutil.rmtree(staging_dir)
        raise
    result = verify_release(final_dir, final_manifest, git_repo=repo)
    if _sha256(final_tar) != manifest["archive_sha256"]:
        raise ValueError("promoted release archive drifted")
    result.update(
        archive_ref=str(final_tar),
        archive_sha256=manifest["archive_sha256"],
        idempotent=False,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--verify-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--git-repo", type=Path)
    args = parser.parse_args()
    if args.verify_dir or args.manifest:
        if args.verify_dir is None or args.manifest is None:
            parser.error("--verify-dir and --manifest must be supplied together")
        result = verify_release(
            args.verify_dir.resolve(),
            args.manifest.resolve(),
            git_repo=args.git_repo,
        )
    else:
        result = build_release(args.repo, args.release_root, args.revision)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
