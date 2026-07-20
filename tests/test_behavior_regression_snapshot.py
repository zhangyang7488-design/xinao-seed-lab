from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.prepare_behavior_regression_snapshot import create_snapshot


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fixture_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "AGENTS.md": "stable pointer\n",
        "pyproject.toml": "[project]\nname='fixture'\nversion='0'\n",
        "uv.lock": "version = 1\n",
        "scripts/run_behavior_regression.ps1": "# runner\n",
        "scripts/prepare_behavior_regression_snapshot.py": "# helper\n",
        "scripts/select_behavior_regression_incremental.py": "# helper\n",
        "tests/test_behavior_regression_snapshot.py": "# test\n",
        "tests/test_behavior_regression_incremental.py": "# test\n",
        "tests/test_repo_safety.py": "# test\n",
        "evals/behavior_regression/catalog.json": "{}\n",
        "evals/context_intent_alignment/promptfooconfig.yaml": (
            "providers:\n  - config:\n      working_dir: ../..\n"
        ),
        "evals/context_intent_alignment/cases.yaml": "[]\n",
        "evals/context_intent_alignment/prompt.txt": "prompt\n",
        "unrelated/tracked.txt": "audit only\n",
        ".gitignore": "ignored.txt\n",
    }
    for relative, value in files.items():
        _write(root / relative, value)
    _write(root / "untracked.txt", "included audit input\n")
    _write(root / "ignored.txt", "must not be copied\n")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


def test_context_snapshot_is_immutable_and_effective_tree_is_sparse(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(repo, output, "context")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = Path(manifest["raw_root"])
    effective = Path(manifest["effective_root"])

    assert (raw / "unrelated/tracked.txt").read_text(encoding="utf-8") == "audit only\n"
    assert (raw / "untracked.txt").exists()
    assert not (raw / "ignored.txt").exists()
    assert not (effective / "unrelated/tracked.txt").exists()
    assert (effective / "AGENTS.md").exists()
    assert (effective / ".git").exists()
    assert manifest["effective_git_head"]
    config = effective / "evals/context_intent_alignment/promptfooconfig.yaml"
    assert (config.parent / "../..").resolve() == effective.resolve()

    identity = manifest["identity_sha256"]
    _write(repo / "evals/context_intent_alignment/prompt.txt", "changed live tree\n")
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["identity_sha256"] == identity
    assert (effective / "evals/context_intent_alignment/prompt.txt").read_text(
        encoding="utf-8"
    ) == "prompt\n"


def test_external_cache_is_copied_and_rebound_for_deep_profile(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    for relative in (
        "evals/codex_capability",
        "evals/proactive_mature_first",
        "evals/mature_capability_recall",
        "evals/thin_localization/fixture_template",
    ):
        _write(repo / relative / "placeholder.txt", "x\n")
    for relative in (
        "tests/test_open_world_reuse_behavior.py",
        "tests/test_repo_safety.py",
        "tests/test_behavior_regression_snapshot.py",
    ):
        _write(repo / relative, "# test\n")
    external = tmp_path / "external.json"
    _write(external, "{}\n")
    config = repo / "evals/mature_capability_recall/promptfooconfig.live.yaml"
    _write(config, f"discovery_cache_path: {external}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(repo, output, "deep", external_cache=external)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective_config = (
        Path(manifest["effective_root"])
        / "evals/mature_capability_recall/promptfooconfig.live.yaml"
    ).read_text(encoding="utf-8")
    assert str(external) not in effective_config
    assert "/src/x/live_discovery_cache/external.json" in effective_config.replace("\\", "/")
    assert manifest["external_files"][0]["sha256"]
