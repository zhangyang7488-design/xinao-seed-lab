#!/usr/bin/env python3
"""Cross-platform local entry for the repository's CI hygiene gates.

Default mode is non-mutating and matches the root remote hygiene cone:

    uv run ruff check <ROOT_PATHS>
    uv run ruff format --check <ROOT_PATHS>
    uv run python -m compileall -q <ROOT_PATHS>

Lint and format always both run so one failure cannot hide the other.

Modes:
  (default)     Root hygiene only (fast local default).
  --projects    Also run each project-local Ruff cone in its own cwd/lock/config.
  --all         Alias for root + projects (full remote hygiene parity with CI).
  --fix         Optional local repair only: ruff check --fix + ruff format
                (still non-policy; does not rewrite CI).

Full remote hygiene parity (root + every project-local Ruff cone):

    uv run python scripts/run_ci_hygiene.py --all

Root-only local check (same cone as the root-hygiene CI job):

    uv run python scripts/run_ci_hygiene.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# Exact root cone gated by .github/workflows/ci.yml root-hygiene job.
ROOT_PATHS: tuple[str, ...] = (
    "services",
    "scripts",
    "tests",
    "skills/xinao/scripts",
    "docker/xinao-researcher",
)

# Project cones use each project's own working directory, lock, and Ruff config.
# Paths match the project-verify matrix ruff_paths in .github/workflows/ci.yml.
PROJECT_CONES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("dual-brain-coordination", "projects/dual-brain-coordination", (".",)),
    ("xinao-market-lab", "projects/xinao-market-lab", (".",)),
    (
        "g4-hidden-capability-seam",
        "projects/g4-hidden-capability-seam",
        ("src", "adapters", "tests"),
    ),
    (
        "xinao-discovery",
        "xinao_discovery",
        ("src/xinao/single_home", "tests/unit/single_home"),
    ),
    (
        "discovery-capability",
        "xinao_discovery",
        ("src/xinao/capability", "tests/unit/capability"),
    ),
    (
        "discovery-science-parent",
        "xinao_discovery",
        (
            "src/xinao/science",
            "src/xinao/world/builder.py",
            "tests/unit/science",
            "tests/contract/test_world.py",
        ),
    ),
    (
        "discovery-domain-admission",
        "xinao_discovery",
        (
            "src/xinao/admission",
            "scripts/register/formal_vertical.py",
            "tests/unit/admission",
            "tests/unit/ledger/test_formal_vertical_registration.py",
        ),
    ),
    (
        "discovery-operational-assurance",
        "xinao_discovery",
        ("src/xinao/assurance", "tests/unit/assurance"),
    ),
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class StepResult:
    label: str
    returncode: int
    argv: tuple[str, ...]


def _default_runner(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        check=False,
    )


def _uv_run(*parts: str) -> tuple[str, ...]:
    return ("uv", "run", *parts)


def run_root_hygiene(
    *,
    repo_root: Path,
    fix: bool = False,
    runner: CommandRunner = _default_runner,
) -> list[StepResult]:
    """Run root ruff check, format, and compileall. Lint and format always both run."""
    paths = list(ROOT_PATHS)
    results: list[StepResult] = []

    if fix:
        lint_argv = _uv_run("ruff", "check", "--fix", *paths)
        format_argv = _uv_run("ruff", "format", *paths)
    else:
        lint_argv = _uv_run("ruff", "check", *paths)
        format_argv = _uv_run("ruff", "format", "--check", *paths)

    # Always attempt both; do not short-circuit on the first failure.
    lint_proc = runner(lint_argv, cwd=repo_root)
    results.append(StepResult("root ruff check", lint_proc.returncode, lint_argv))

    format_proc = runner(format_argv, cwd=repo_root)
    results.append(StepResult("root ruff format", format_proc.returncode, format_argv))

    if not fix:
        compile_argv = _uv_run("python", "-m", "compileall", "-q", *paths)
        compile_proc = runner(compile_argv, cwd=repo_root)
        results.append(StepResult("root compileall", compile_proc.returncode, compile_argv))

    return results


def run_project_hygiene(
    *,
    repo_root: Path,
    fix: bool = False,
    runner: CommandRunner = _default_runner,
) -> list[StepResult]:
    """Run each project cone under that project's cwd/lock/config (never root Ruff)."""
    results: list[StepResult] = []
    for name, rel_path, ruff_paths in PROJECT_CONES:
        project_root = repo_root / rel_path
        path_args = list(ruff_paths)
        if fix:
            lint_argv = _uv_run("ruff", "check", "--fix", *path_args)
            format_argv = _uv_run("ruff", "format", *path_args)
        else:
            lint_argv = _uv_run("ruff", "check", *path_args)
            format_argv = _uv_run("ruff", "format", "--check", *path_args)

        lint_proc = runner(lint_argv, cwd=project_root)
        results.append(StepResult(f"{name} ruff check", lint_proc.returncode, lint_argv))
        format_proc = runner(format_argv, cwd=project_root)
        results.append(StepResult(f"{name} ruff format", format_proc.returncode, format_argv))
    return results


def aggregate_returncode(results: Sequence[StepResult]) -> int:
    for result in results:
        if result.returncode != 0:
            return result.returncode if result.returncode > 0 else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run repository CI hygiene gates locally. "
            "Default is root-only non-mutating check. "
            "Use --all for full remote hygiene parity (root + project cones)."
        )
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--projects",
        action="store_true",
        help="Also run project-local Ruff cones in each project's own directory.",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Root + every project-local Ruff cone (full remote hygiene parity).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Optional local repair: ruff check --fix and ruff format (mutating).",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path | None = None,
    runner: CommandRunner = _default_runner,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = repo_root if repo_root is not None else Path(__file__).resolve().parents[1]
    include_projects = bool(args.projects or args.all)

    results: list[StepResult] = []
    results.extend(run_root_hygiene(repo_root=root, fix=args.fix, runner=runner))
    if include_projects:
        results.extend(run_project_hygiene(repo_root=root, fix=args.fix, runner=runner))

    for result in results:
        status = "ok" if result.returncode == 0 else f"exit {result.returncode}"
        print(f"[{status}] {result.label}: {' '.join(result.argv)}", file=stdout)

    code = aggregate_returncode(results)
    if code != 0:
        print("ci hygiene failed", file=stderr)
    else:
        print("ci hygiene passed", file=stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
