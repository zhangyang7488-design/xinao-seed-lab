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
import stat
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


@dataclass(frozen=True)
class FrozenSourceInput:
    source_input: SourceInput
    source: Path
    state: dict[str, object]


class SourceSnapshotConflict(RuntimeError):
    """A selected input no longer matches the state chosen for this snapshot."""


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
    relative_paths = (
        os.fsdecode(item).replace("\\", "/") for item in completed.stdout.split(b"\0") if item
    )
    # ``git ls-files --cached`` also reports tracked paths deleted only in the
    # working tree.  A source snapshot describes the live tree, so those paths
    # must disappear instead of making cleanup impossible until staging.
    return sorted(relative for relative in relative_paths if (repo_root / Path(relative)).is_file())


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
    shutil.copy2(source, target)


def _mode(st_mode: int) -> int:
    return stat.S_IMODE(st_mode)


def _regular_file_state(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise SourceSnapshotConflict(f"selected input changed type while hashing: {path}")
            digest = hashlib.sha256()
            size_bytes = 0
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size_bytes += len(chunk)
            finished = os.fstat(handle.fileno())
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise SourceSnapshotConflict(f"selected input disappeared while hashing: {path}") from exc
    if (
        not stat.S_ISREG(finished.st_mode)
        or _mode(opened.st_mode) != _mode(finished.st_mode)
        or opened.st_size != finished.st_size
        or size_bytes != finished.st_size
    ):
        raise SourceSnapshotConflict(f"selected input changed while hashing: {path}")
    return {
        "type": "file",
        "mode": _mode(finished.st_mode),
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
    }


def _link_state(path: Path, st_mode: int) -> dict[str, object]:
    try:
        target_bytes = os.fsencode(os.readlink(path))
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise SourceSnapshotConflict(
            f"selected input link disappeared while inspecting: {path}"
        ) from exc
    return {
        "type": "symlink",
        "mode": _mode(st_mode),
        "size_bytes": len(target_bytes),
        "sha256": hashlib.sha256(target_bytes).hexdigest(),
    }


def _directory_entries(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def visit(directory: Path, relative_root: Path) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise SourceSnapshotConflict(
                f"selected input directory changed while inspecting: {directory}"
            ) from exc
        for child in children:
            relative = relative_root / child.name
            if "__pycache__" in relative.parts:
                continue
            try:
                child_stat = child.lstat()
            except (FileNotFoundError, NotADirectoryError) as exc:
                raise SourceSnapshotConflict(
                    f"selected input entry changed while inspecting: {child}"
                ) from exc
            row: dict[str, object] = {
                "path": relative.as_posix(),
                "mode": _mode(child_stat.st_mode),
            }
            if stat.S_ISREG(child_stat.st_mode):
                row.update(_regular_file_state(child))
            elif stat.S_ISDIR(child_stat.st_mode):
                row["type"] = "directory"
                rows.append(row)
                visit(child, relative)
                continue
            elif stat.S_ISLNK(child_stat.st_mode):
                row.update(_link_state(child, child_stat.st_mode))
            else:
                row.update({"type": "special", "sha256": None})
            rows.append(row)

    visit(root, Path())
    return sorted(rows, key=lambda row: str(row["path"]))


def _capture_source_state(path: Path) -> dict[str, object]:
    try:
        root_stat = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return {"type": "ABSENT", "mode": None, "sha256": None}
    if stat.S_ISREG(root_stat.st_mode):
        return _regular_file_state(path)
    if stat.S_ISDIR(root_stat.st_mode):
        entries = _directory_entries(path)
        return {
            "type": "directory",
            "mode": _mode(root_stat.st_mode),
            "sha256": _canonical_sha256(entries),
            "entries": entries,
        }
    if stat.S_ISLNK(root_stat.st_mode):
        return _link_state(path, root_stat.st_mode)
    return {
        "type": "special",
        "mode": _mode(root_stat.st_mode),
        "sha256": None,
    }


def _freeze_source_inputs(inputs: list[SourceInput]) -> list[FrozenSourceInput]:
    frozen: list[FrozenSourceInput] = []
    for source_input in inputs:
        source = source_input.path.resolve(strict=False)
        frozen.append(
            FrozenSourceInput(
                source_input=source_input,
                source=source,
                state=_capture_source_state(source),
            )
        )
    return frozen


def _assert_source_state(frozen: FrozenSourceInput, *, phase: str) -> None:
    actual = _capture_source_state(frozen.source)
    if actual != frozen.state:
        raise SourceSnapshotConflict(
            "selected input drifted during "
            f"{phase}: {frozen.source}; "
            f"expected={_canonical_sha256(frozen.state)}; "
            f"actual={_canonical_sha256(actual)}"
        )


def _assert_source_states(frozen_inputs: list[FrozenSourceInput], *, phase: str) -> None:
    for frozen in frozen_inputs:
        _assert_source_state(frozen, phase=phase)


def _assert_copyable_state(frozen: FrozenSourceInput) -> None:
    state_type = frozen.state["type"]
    if state_type == "ABSENT":
        raise FileNotFoundError(frozen.source)
    if state_type not in {"file", "directory"}:
        raise SourceSnapshotConflict(
            f"unsupported selected input type {state_type}: {frozen.source}"
        )
    if state_type == "directory":
        unsupported = [
            row for row in frozen.state["entries"] if row["type"] not in {"file", "directory"}
        ]
        if unsupported:
            raise SourceSnapshotConflict(
                f"unsupported entry in selected input tree: {frozen.source}"
            )


def _copy_frozen_source(frozen: FrozenSourceInput, target: Path) -> None:
    _assert_copyable_state(frozen)
    if frozen.state["type"] == "file":
        _copy_file(frozen.source, target)
    else:
        target.mkdir(parents=True, exist_ok=True)
        entries = frozen.state["entries"]
        directories = [row for row in entries if row["type"] == "directory"]
        files = [row for row in entries if row["type"] == "file"]
        for row in sorted(directories, key=lambda item: len(Path(str(item["path"])).parts)):
            (target / str(row["path"])).mkdir(parents=True, exist_ok=True)
        for row in files:
            relative = Path(str(row["path"]))
            _copy_file(frozen.source / relative, target / relative)
        for row in sorted(
            directories,
            key=lambda item: len(Path(str(item["path"])).parts),
            reverse=True,
        ):
            relative = Path(str(row["path"]))
            shutil.copystat(
                frozen.source / relative,
                target / relative,
                follow_symlinks=False,
            )
        shutil.copystat(frozen.source, target, follow_symlinks=False)
    copied_state = _capture_source_state(target)
    if copied_state != frozen.state:
        raise SourceSnapshotConflict(
            "copied input does not match its frozen source state: "
            f"{frozen.source}; expected={_canonical_sha256(frozen.state)}; "
            f"copied={_canonical_sha256(copied_state)}"
        )


def _profile_flags(
    profile: str, *, domain: str, case_pattern: str, failed_from: str
) -> dict[str, bool]:
    return {
        "capability": profile in {"capability", "smoke", "core", "deep"}
        and not domain
        and not case_pattern
        and not failed_from,
        "context": False,
        "intent": profile in {"intent", "smoke", "core", "deep"},
        "external_reality": profile in {"external", "core", "deep"},
        "reconstitution": profile in {"reconstitution", "core", "deep"},
        "surface": profile in {"surface", "core", "deep"},
        "proactive": profile in {"proactive", "core", "deep"},
        "recall_replay": profile in {"core", "deep", "reuse"},
        "recall_live": profile in {"deep", "reuse"},
        "thin": profile in {"core", "deep", "reuse"},
        "productivity": profile in {"productivity", "core", "deep"},
        "native_subagent": profile == "subagent",
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
    codex_home: Path | None = None,
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
        (
            "evals/behavior_regression/capability_lineage.v1.json",
            "capability_lineage_migration_preflight",
        ),
        (
            "tests/test_behavior_capability_lineage.py",
            "capability_lineage_migration_preflight_tests",
        ),
        (
            "scripts/build_codex_productivity_recovery.py",
            "codex_productivity_recovery_builder",
        ),
        (
            "infra/codex_productivity_recovery/v2/manifest.v2.json",
            "codex_productivity_recovery_v2_manifest",
        ),
        (
            "infra/codex_productivity_recovery/v2/codex-productivity-recovery.non-pi.v2.zip",
            "codex_productivity_recovery_v2_archive",
        ),
        (
            "tests/test_codex_productivity_recovery.py",
            "codex_productivity_recovery_tests",
        ),
        (
            "evals/intent_continuity_baseline/decision_model.v1.json",
            "intent_continuity_baseline",
        ),
        (
            "evals/intent_continuity_baseline/consumer_coverage.v1.json",
            "intent_action_consumer_coverage",
        ),
        (
            "evals/intent_continuity_baseline/BASELINE.md",
            "intent_action_baseline_documentation",
        ),
        (
            "tests/test_intent_action_consumer_coverage.py",
            "intent_action_coverage_tests",
        ),
    ]
    if flags["static"]:
        relative_inputs.append(
            ("tests/test_open_world_reuse_behavior.py", "static_assertion_tests")
        )
    if flags["context"] or flags["proactive"]:
        relative_inputs.append(("tests/test_repo_safety.py", "repository_safety_tests"))
    if flags["intent"]:
        relative_inputs.extend(
            (
                ("tests/test_parent_frame_admission.py", "parent_frame_admission_tests"),
                ("evals/parent_frame_admission", "parent_frame_admission"),
            )
        )
    if flags["surface"]:
        relative_inputs.extend(
            (
                (
                    "tests/test_parent_continuity_user_surface.py",
                    "parent_continuity_user_surface_tests",
                ),
                (
                    "evals/parent_continuity_user_surface",
                    "parent_continuity_user_surface_eval",
                ),
            )
        )
    if flags["external_reality"]:
        relative_inputs.extend(
            (
                (
                    "tests/test_external_reality_research.py",
                    "external_reality_research_tests",
                ),
                (
                    "evals/external_reality_research",
                    "external_reality_research_eval",
                ),
            )
        )
    if flags["reconstitution"]:
        relative_inputs.extend(
            (
                (
                    "tests/test_recursive_frame_reconstitution.py",
                    "recursive_frame_reconstitution_tests",
                ),
                (
                    "evals/recursive_frame_reconstitution",
                    "recursive_frame_reconstitution_eval",
                ),
            )
        )
    if flags["native_subagent"]:
        relative_inputs.append(
            (
                "tests/test_native_subagent_trajectory.py",
                "native_subagent_trajectory_tests",
            )
        )
    if flags["productivity"]:
        relative_inputs.append(
            (
                "tests/test_productive_action_trajectory.py",
                "productive_action_trajectory_tests",
            )
        )
    for enabled, relative, role in (
        (flags["capability"], "evals/codex_capability", "capability_eval"),
        (flags["proactive"], "evals/proactive_mature_first", "proactive_eval"),
        (
            flags["recall_replay"] or flags["recall_live"],
            "evals/mature_capability_recall",
            "mature_capability_recall_eval",
        ),
        (flags["thin"], "evals/thin_localization", "thin_localization_eval"),
        (
            flags["productivity"],
            "evals/productive_action_trajectory",
            "productive_action_trajectory_eval",
        ),
        (
            flags["native_subagent"],
            "evals/native_subagent_trajectory",
            "native_subagent_trajectory_eval",
        ),
    ):
        if enabled:
            relative_inputs.append((relative, role))

    inputs = [
        SourceInput(repo_root / relative, role, relative.replace("\\", "/"))
        for relative, role in relative_inputs
    ]
    if (
        flags["intent"]
        or flags["external_reality"]
        or flags["reconstitution"]
        or flags["surface"]
        or flags["productivity"]
    ):
        if codex_home is None:
            raise ValueError(
                "codex_home is required for intent, external-reality, reconstitution, surface, and productive-action profiles"
            )
        inputs.append(
            SourceInput(
                codex_home / "AGENTS.md",
                "global_working_kernel",
                "external/global_codex_home/AGENTS.md",
            )
        )
    if flags["external_reality"]:
        inputs.append(
            SourceInput(
                codex_home / "skills" / "research-external-reality",
                "external_reality_research_skill",
                "external/global_codex_home/skills/research-external-reality",
            )
        )
    if flags["reconstitution"]:
        inputs.append(
            SourceInput(
                codex_home / "skills" / "conduct-xinao-native-research",
                "xinao_native_research_skill",
                "external/global_codex_home/skills/conduct-xinao-native-research",
            )
        )
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
    subprocess.run(
        ["git", "-C", str(effective_root), "config", "core.longpaths", "true"],
        check=True,
    )
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
    codex_home: Path | None = None,
) -> Path:
    repo_root = repo_root.resolve()
    output_root = output_root.resolve()
    source_root = output_root / "src"
    raw_root = source_root / "r"
    effective_root = source_root / "e"
    external_root = source_root / "x"
    inputs = selected_inputs(
        repo_root,
        profile,
        domain=domain,
        case_pattern=case_pattern,
        failed_from=failed_from,
        external_cache=external_cache,
        codex_home=codex_home,
    )
    frozen_inputs = _freeze_source_inputs(inputs)
    _assert_source_states(frozen_inputs, phase="initial source freeze")
    for path in (raw_root, effective_root, external_root):
        path.mkdir(parents=True, exist_ok=False)

    raw_files = _git_files(repo_root)
    for relative in raw_files:
        _copy_file(_safe_repo_file(repo_root, relative), raw_root / relative)
    _assert_source_states(frozen_inputs, phase="raw-tree capture")

    input_rows: list[dict[str, object]] = []
    external_rebindings: list[tuple[str, str]] = []
    for frozen in frozen_inputs:
        source_input = frozen.source_input
        source = frozen.source
        _assert_source_state(frozen, phase=f"pre-copy for {source_input.role}")
        try:
            source.relative_to(repo_root)
            target = effective_root / source_input.logical_path
        except ValueError:
            target = external_root / source_input.role / source.name
            if source_input.role == "live_discovery_cache":
                external_rebindings.append((str(source), str(target)))
        _copy_frozen_source(frozen, target)
        _assert_source_state(frozen, phase=f"post-copy for {source_input.role}")
        input_rows.append(
            {
                "role": source_input.role,
                "logical_path": source_input.logical_path,
                "source_path": str(source),
                "snapshot_path": str(target),
                "source_state": frozen.state,
                "source_state_sha256": _canonical_sha256(frozen.state),
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
    source_state_rows = [
        {
            "role": row["role"],
            "logical_path": row["logical_path"],
            "source_state": row["source_state"],
            "source_state_sha256": row["source_state_sha256"],
        }
        for row in input_rows
    ]
    identity_document = {
        "profile": profile,
        "domain": domain,
        "case_pattern": case_pattern,
        "failed_from": bool(failed_from),
        "source_inputs": source_state_rows,
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
    _assert_source_states(frozen_inputs, phase="snapshot finalization")
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
        choices=(
            "capability",
            "smoke",
            "core",
            "deep",
            "proactive",
            "reuse",
            "intent",
            "external",
            "reconstitution",
            "surface",
            "productivity",
            "subagent",
        ),
    )
    parser.add_argument("--domain", default="")
    parser.add_argument("--case-pattern", default="")
    parser.add_argument("--failed-from", default="")
    parser.add_argument("--external-cache", type=Path, default=EXTERNAL_CACHE_DEFAULT)
    parser.add_argument("--codex-home", type=Path)
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
        codex_home=args.codex_home,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
