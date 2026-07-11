"""Ripgrep local scan helpers — extracted from codex_s_light_research_loop for L4 thin bind."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def default_local_roots(repo: Path) -> list[str]:
    del repo
    return [
        "AGENTS.md",
        "CODEX_S_L0.md",
        "services",
        "scripts",
        "src",
        "tests",
        "docs",
        "contracts",
    ]


def scan_root_path(repo: Path, root_text: str) -> Path:
    root = Path(root_text)
    return root if root.is_absolute() else repo / root


def rg_root_arg(repo: Path, root_text: str) -> str:
    root = Path(root_text)
    return str(root) if root.is_absolute() else root_text


def scan_result_paths(repo: Path, path_text: str) -> tuple[str, str]:
    path = Path(path_text)
    absolute = path.resolve() if path.is_absolute() else (repo / path).resolve()
    try:
        repo_relative = str(absolute.relative_to(repo.resolve()))
    except ValueError:
        repo_relative = str(absolute)
    return str(absolute), repo_relative


def fallback_local_scan(
    repo: Path, roots: list[str], query: str, max_results: int
) -> list[dict[str, Any]]:
    query_lower = query.lower()
    results: list[dict[str, Any]] = []
    for root_text in roots:
        root = scan_root_path(repo, root_text)
        files = [root] if root.is_file() else list(root.rglob("*")) if root.is_dir() else []
        for path in files:
            if len(results) >= max_results:
                return results
            if not path.is_file() or path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".ico",
                ".exe",
            }:
                continue
            text = read_text(path)
            if not text:
                continue
            for index, line in enumerate(text.splitlines(), start=1):
                if query_lower in line.lower():
                    results.append(
                        {
                            "path": str(path.resolve()),
                            "repo_relative_path": scan_result_paths(repo, str(path))[1],
                            "line": index,
                            "snippet": line.strip()[:700],
                            "query": query,
                        }
                    )
                    break
    return results


def run_rg_scan(repo: Path, roots: list[str], query: str, max_results: int) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    scan_roots = roots or default_local_roots(repo)
    rg_roots = [rg_root_arg(repo, root) for root in scan_roots]
    cmd = ["rg", "-n", "--no-heading", "--color", "never", "-S", "--", query, *rg_roots]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return fallback_local_scan(repo, scan_roots, query, max_results)
    if completed.returncode not in {0, 1}:
        return fallback_local_scan(repo, scan_roots, query, max_results)
    results: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        if len(results) >= max_results:
            break
        match = re.match(r"^(.+?):(\d+):(.*)$", line)
        if not match:
            continue
        path_text, line_no, snippet = match.groups()
        absolute_path, repo_relative_path = scan_result_paths(repo, path_text)
        results.append(
            {
                "path": absolute_path,
                "repo_relative_path": repo_relative_path,
                "line": int(line_no),
                "snippet": snippet.strip()[:700],
                "query": query,
            }
        )
    return results
