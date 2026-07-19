#!/usr/bin/env python3
"""Freeze one behavior-regression run before any model call.

The raw tree is an audit cut of tracked plus non-ignored untracked repository
files.  The effective tree contains only files consumed by the selected
profile.  External inputs are copied under ``src/x`` and rebound in the
effective configuration.  Nothing here selects a model or owns run state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = "xinao.behavior_regression_source_snapshot.v1"
EXTERNAL_CACHE_DEFAULT = Path(
    r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\manifests\github_external_mature_all_repos.json"
)


@dataclass(frozen=True)
class SourceInput:
    path: Path
    role: str
    logical_path: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git_files(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return sorted(
        os.fsdecode(item).replace("\\", "/") for item in completed.stdout.split(b"\0") if item
    )


def _safe_repo_file(repo_root: Path, relative: str) -> Path:
    candidate = (repo_root / Path(relative)).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"repository path escapes root: {relative}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _copy_tree_files(source: Path, target: Path) -> None:
    if source.is_file():
        _copy_file(source, target)
        return
    if not source.is_dir():
        raise FileNotFoundError(source)
    for file_path in sorted(path for path in source.rglob("*") if path.is_file()):
        if "__pycache__" in file_path.parts:
            continue
        _copy_file(file_path, target / file_path.relative_to(source))


def _profile_flags(
    profile: str, *, domain: str, case_pattern: str, failed_from: str
) -> dict[str, bool]:
    return {
        "capability": profile in {"capability", "smoke", "core", "deep"}
        and not domain
        and not case_pattern
        and not failed_from,
        "context": profile in {"context", "smoke", "core", "deep"},
        "proactive": profile in {"proactive", "core", "deep"},
        "recall_replay": profile in {"core", "deep", "reuse"},
        "recall_live": profile in {"deep", "reuse"},
        "thin": profile in {"core", "deep", "reuse"},
        "static": profile in {"core", "deep", "reuse"} and not failed_from,
    }


def selected_inputs(
    repo_root: Path,
    profile: str,
    *,
    domain: str = "",
    case_pattern: str = "",
    failed_from: str = "",
    external_cache: Path = EXTERNAL_CACHE_DEFAULT,
) -> list[SourceInput]:
    flags = _profile_flags(
        profile,
        domain=domain,
        case_pattern=case_pattern,
        failed_from=failed_from,
    )
    relative_inputs: list[tuple[str, str]] = [
        ("AGENTS.md", "working_agreement"),
        ("pyproject.toml", "python_runtime_contract"),
        ("uv.lock", "python_runtime_lock"),
        ("scripts/run_behavior_regression.ps1", "runner"),
        ("scripts/prepare_behavior_regression_snapshot.py", "snapshot_builder"),
        ("scripts/select_behavior_regression_incremental.py", "incremental_selector"),
        ("tests/test_behavior_regression_snapshot.py", "snapshot_builder_tests"),
        ("tests/test_behavior_regression_incremental.py", "incremental_selector_tests"),
        ("evals/behavior_regression/catalog.json", "catalog"),
    ]
    if flags["static"]:
        relative_inputs.append(
            ("tests/test_open_world_reuse_behavior.py", "static_assertion_tests")
        )
    if flags["context"] or flags["proactive"]:
        relative_inputs.append(("tests/test_repo_safety.py", "repository_safety_tests"))
    for enabled, relative, role in (
        (flags["capability"], "evals/codex_capability", "capability_eval"),
        (flags["context"], "evals/context_intent_alignment", "context_eval"),
        (flags["proactive"], "evals/proactive_mature_first", "proactive_eval"),
        (
            flags["recall_replay"] or flags["recall_live"],
            "evals/mature_capability_recall",
            "mature_capability_recall_eval",
        ),
        (flags["thin"], "evals/thin_localization", "thin_localization_eval"),
    ):
        if enabled:
            relative_inputs.append((relative, role))

    inputs = [
        SourceInput(repo_root / relative, role, relative.replace("\\", "/"))
        for relative, role in relative_inputs
    ]
    if flags["recall_live"]:
        inputs.append(
            SourceInput(
                external_cache,
                "live_discovery_cache",
                f"external/live_discovery_cache/{external_cache.name}",
            )
        )
    return inputs


def _file_rows(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(
            item
            for item in root.rglob("*")
            if item.is_file() and ".git" not in item.relative_to(root).parts
        )
    ]


def _initialize_effective_git(effective_root: Path) -> str:
    subprocess.run(["git", "-C", str(effective_root), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(effective_root), "add", "--all"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(effective_root),
            "-c",
            "user.name=xinao-eval",
            "-c",
            "user.email=xinao-eval@local",
            "commit",
            "--quiet",
            "-m",
            "frozen behavior input",
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(effective_root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def create_snapshot(
    repo_root: Path,
    output_root: Path,
    profile: str,
    *,
    domain: str = "",
    case_pattern: str = "",
    failed_from: str = "",
    external_cache: Path = EXTERNAL_CACHE_DEFAULT,
) -> Path:
    repo_root = repo_root.resolve()
    output_root = output_root.resolve()
    source_root = output_root / "src"
    raw_root = source_root / "r"
    effective_root = source_root / "e"
    external_root = source_root / "x"
    for path in (raw_root, effective_root, external_root):
        path.mkdir(parents=True, exist_ok=False)

    raw_files = _git_files(repo_root)
    for relative in raw_files:
        _copy_file(_safe_repo_file(repo_root, relative), raw_root / relative)

    inputs = selected_inputs(
        repo_root,
        profile,
        domain=domain,
        case_pattern=case_pattern,
        failed_from=failed_from,
        external_cache=external_cache,
    )
    input_rows: list[dict[str, object]] = []
    external_rebindings: list[tuple[str, str]] = []
    for source_input in inputs:
        source = source_input.path.resolve()
        try:
            source.relative_to(repo_root)
            target = effective_root / source_input.logical_path
        except ValueError:
            target = external_root / source_input.role / source.name
            external_rebindings.append((str(source), str(target)))
        _copy_tree_files(source, target)
        input_rows.append(
            {
                "role": source_input.role,
                "logical_path": source_input.logical_path,
                "source_path": str(source),
                "snapshot_path": str(target),
            }
        )

    if external_rebindings:
        config = effective_root / "evals/mature_capability_recall/promptfooconfig.live.yaml"
        content = config.read_text(encoding="utf-8")
        for original, rebound in external_rebindings:
            if original not in content:
                raise ValueError(f"external input is not bound by live config: {original}")
            content = content.replace(original, rebound.replace("\\", "/"))
        config.write_text(content, encoding="utf-8", newline="")

    effective_git_head = _initialize_effective_git(effective_root)
    raw_rows = _file_rows(raw_root)
    effective_rows = _file_rows(effective_root)
    external_rows = _file_rows(external_root)
    identity_document = {
        "profile": profile,
        "domain": domain,
        "case_pattern": case_pattern,
        "failed_from": bool(failed_from),
        "raw_files": raw_rows,
        "effective_files": effective_rows,
        "external_files": external_rows,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "repo_root": str(repo_root),
        "raw_root": str(raw_root),
        "effective_root": str(effective_root),
        "external_root": str(external_root),
        "effective_git_head": effective_git_head,
        "profile": profile,
        "domain": domain,
        "case_pattern": case_pattern,
        "failed_from": failed_from,
        "source_inputs": input_rows,
        "raw_files": raw_rows,
        "effective_files": effective_rows,
        "external_files": external_rows,
        "identity_sha256": _canonical_sha256(identity_document),
    }
    manifest_path = source_root / "source-snapshot.v1.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    return manifest_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--profile",
        required=True,
        choices=("capability", "smoke", "core", "deep", "context", "proactive", "reuse"),
    )
    parser.add_argument("--domain", default="")
    parser.add_argument("--case-pattern", default="")
    parser.add_argument("--failed-from", default="")
    parser.add_argument("--external-cache", type=Path, default=EXTERNAL_CACHE_DEFAULT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = create_snapshot(
        args.repo_root,
        args.output_root,
        args.profile,
        domain=args.domain,
        case_pattern=args.case_pattern,
        failed_from=args.failed_from,
        external_cache=args.external_cache,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
