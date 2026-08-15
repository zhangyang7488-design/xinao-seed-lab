from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import scripts.prepare_behavior_regression_snapshot as snapshot_builder
from scripts.prepare_behavior_regression_snapshot import (
    FrozenSourceInput,
    SourceInput,
    SourceSnapshotConflict,
    create_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


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
        "evals/behavior_regression/capability_lineage.v1.json": "{}\n",
        "tests/test_behavior_capability_lineage.py": "# test\n",
        "evals/semantic_implication_regression/source_contract.v1.json": "{}\n",
        "evals/semantic_implication_regression/cases.yaml": "[]\n",
        "scripts/run_semantic_implication_regression_eval.ps1": "# cold runner\n",
        "tests/test_semantic_implication_regression.py": "# cold test\n",
        "scripts/build_codex_productivity_recovery.py": "# helper\n",
        "infra/codex_productivity_recovery/v2/manifest.v2.json": "{}\n",
        "infra/codex_productivity_recovery/v2/codex-productivity-recovery.non-pi.v2.zip": "archive\n",
        "tests/test_codex_productivity_recovery.py": "# test\n",
        "evals/intent_continuity_baseline/decision_model.v1.json": "{}\n",
        "evals/intent_continuity_baseline/consumer_coverage.v1.json": "{}\n",
        "evals/intent_continuity_baseline/BASELINE.md": "# baseline\n",
        "tests/test_intent_action_consumer_coverage.py": "# test\n",
        "unrelated/tracked.txt": "audit only\n",
        "unrelated/deleted.txt": "must follow live deletion\n",
        ".gitignore": "ignored.txt\n",
    }
    for relative, value in files.items():
        _write(root / relative, value)
    _write(root / "untracked.txt", "included audit input\n")
    _write(root / "ignored.txt", "must not be copied\n")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    (root / "unrelated/deleted.txt").unlink()
    return root


def test_baseline_snapshot_is_immutable_and_effective_tree_is_sparse(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(repo, output, "context")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = Path(manifest["raw_root"])
    effective = Path(manifest["effective_root"])

    assert (raw / "unrelated/tracked.txt").read_text(encoding="utf-8") == "audit only\n"
    assert not (raw / "unrelated/deleted.txt").exists()
    assert (raw / "untracked.txt").exists()
    assert not (raw / "ignored.txt").exists()
    assert not (effective / "unrelated/tracked.txt").exists()
    assert (effective / "AGENTS.md").exists()
    assert (effective / ".git").exists()
    assert manifest["effective_git_head"]
    longpaths = subprocess.run(
        ["git", "-C", str(effective), "config", "--bool", "core.longpaths"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    assert longpaths == "true"
    autocrlf = subprocess.run(
        ["git", "-C", str(effective), "config", "--bool", "core.autocrlf"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    assert autocrlf == "false"
    model = effective / "evals/intent_continuity_baseline/decision_model.v1.json"
    assert model.read_text(encoding="utf-8") == "{}\n"
    assert (effective / "evals/intent_continuity_baseline/consumer_coverage.v1.json").exists()
    assert (effective / "evals/intent_continuity_baseline/BASELINE.md").exists()
    assert (effective / "evals/behavior_regression/capability_lineage.v1.json").exists()
    assert (effective / "tests/test_behavior_capability_lineage.py").exists()
    assert (
        effective / "infra/codex_productivity_recovery/v2/codex-productivity-recovery.non-pi.v2.zip"
    ).exists()
    assert (effective / "tests/test_codex_productivity_recovery.py").exists()
    assert not (effective / "evals/semantic_implication_regression").exists()
    assert not (effective / "scripts/run_semantic_implication_regression_eval.ps1").exists()

    identity = manifest["identity_sha256"]
    agents_row = next(
        row for row in manifest["source_inputs"] if row["role"] == "working_agreement"
    )
    agents_bytes = (repo / "AGENTS.md").read_bytes()
    assert agents_row["source_state"] == {
        "type": "file",
        "mode": (repo / "AGENTS.md").stat().st_mode & 0o7777,
        "size_bytes": len(agents_bytes),
        "sha256": hashlib.sha256(agents_bytes).hexdigest(),
    }
    assert len(agents_row["source_state_sha256"]) == 64
    _write(repo / "evals/intent_continuity_baseline/decision_model.v1.json", "changed\n")
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["identity_sha256"] == identity
    assert model.read_text(encoding="utf-8") == "{}\n"


def test_snapshot_fails_closed_when_selected_input_changes_during_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _fixture_repo(tmp_path)
    output = tmp_path / "run"
    output.mkdir()
    original_copy = snapshot_builder._copy_frozen_source
    changed = False

    def copy_then_change(frozen: FrozenSourceInput, target: Path) -> None:
        nonlocal changed
        original_copy(frozen, target)
        if not changed and frozen.source_input.role == "working_agreement":
            source_bytes = bytearray(frozen.source.read_bytes())
            source_bytes[0] ^= 1
            frozen.source.write_bytes(source_bytes)
            changed = True

    monkeypatch.setattr(snapshot_builder, "_copy_frozen_source", copy_then_change)

    with pytest.raises(SourceSnapshotConflict, match="selected input drifted"):
        create_snapshot(repo, output, "context")

    assert changed
    assert not (output / "src/source-snapshot.v1.json").exists()


def test_snapshot_fails_closed_when_frozen_absence_is_occupied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _fixture_repo(tmp_path)
    output = tmp_path / "run"
    output.mkdir()
    absent = repo / "late-selected-input.txt"
    original_selected_inputs = snapshot_builder.selected_inputs
    original_git_files = snapshot_builder._git_files

    def select_with_absent(*args: object, **kwargs: object) -> list[SourceInput]:
        return [
            *original_selected_inputs(*args, **kwargs),
            SourceInput(absent, "late_selected_input", "late-selected-input.txt"),
        ]

    def list_then_occupy(repo_root: Path) -> list[str]:
        listed = original_git_files(repo_root)
        absent.write_bytes(b"occupied\n")
        return listed

    monkeypatch.setattr(snapshot_builder, "selected_inputs", select_with_absent)
    monkeypatch.setattr(snapshot_builder, "_git_files", list_then_occupy)

    with pytest.raises(SourceSnapshotConflict, match="raw-tree capture"):
        create_snapshot(repo, output, "context")

    assert absent.is_file()
    assert not (output / "src/source-snapshot.v1.json").exists()


def test_semantic_implication_runner_owns_a_separate_exact_external_snapshot() -> None:
    runner = (REPO_ROOT / "scripts" / "run_semantic_implication_regression_eval.ps1").read_text(
        encoding="utf-8"
    )
    assert "source_contract.v1.json" in runner
    assert "$sourceHashBefore" in runner
    assert "$sourceHashAfter" in runner
    assert "$snapshotSuiteStatesBefore" in runner
    assert "Assert-CausalFileStatesUnchanged -Before $snapshotSuiteStatesBefore" in runner
    assert "Canonical cold corpus changed while" in runner
    assert "xinao.semantic_implication_source_snapshot.v2" in runner
    assert "source-snapshot.v2.json" in runner
    assert "frozen_suite_files = @($snapshotSuiteStatesBefore)" in runner
    assert "source_snapshot_sha256" in runner
    assert "causal_file_stability_verified = $true" in runner
    assert "D:\\XINAO_RESEARCH_RUNTIME" in runner
    assert "consumer_identity" in runner
    assert "codex_entry_sha256" in runner
    assert "automatic_core_rewrite_allowed = $false" in runner
    assert "run_behavior_regression.ps1" not in runner


def test_external_cache_is_copied_and_rebound_for_deep_profile(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    for relative in (
        "evals/codex_capability",
        "evals/parent_frame_admission",
        "evals/proactive_mature_first",
        "evals/external_reality_research",
        "evals/recursive_frame_reconstitution",
        "evals/parent_continuity_user_surface",
        "evals/mature_capability_recall",
        "evals/thin_localization/fixture_template",
        "evals/productive_action_trajectory/fixture_template",
    ):
        _write(repo / relative / "placeholder.txt", "x\n")
    for relative in (
        "tests/test_open_world_reuse_behavior.py",
        "tests/test_parent_frame_admission.py",
        "tests/test_external_reality_research.py",
        "tests/test_recursive_frame_reconstitution.py",
        "tests/test_parent_continuity_user_surface.py",
        "tests/test_repo_safety.py",
        "tests/test_behavior_regression_snapshot.py",
        "tests/test_productive_action_trajectory.py",
    ):
        _write(repo / relative, "# test\n")
    external = tmp_path / "external.json"
    _write(external, "{}\n")
    codex_home = tmp_path / "codex-home"
    _write(codex_home / "AGENTS.md", "global behavior kernel\n")
    _write(
        codex_home / "skills/research-external-reality/SKILL.md",
        "---\nname: research-external-reality\ndescription: fixture\n---\n",
    )
    _write(
        codex_home / "skills/conduct-xinao-native-research/SKILL.md",
        "---\nname: conduct-xinao-native-research\ndescription: fixture\n---\n",
    )
    config = repo / "evals/mature_capability_recall/promptfooconfig.live.yaml"
    _write(config, f"discovery_cache_path: {external}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(
        repo,
        output,
        "deep",
        external_cache=external,
        codex_home=codex_home,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective = Path(manifest["effective_root"])
    effective_config = (
        effective / "evals/mature_capability_recall/promptfooconfig.live.yaml"
    ).read_text(encoding="utf-8")
    assert str(external) not in effective_config
    assert "/src/x/live_discovery_cache/external.json" in effective_config.replace("\\", "/")
    assert all(row["sha256"] for row in manifest["external_files"])
    roles = {row["role"] for row in manifest["source_inputs"]}
    assert "global_working_kernel" in roles
    assert "external_reality_research_eval" in roles
    assert "external_reality_research_skill" in roles
    assert "recursive_frame_reconstitution_eval" in roles
    assert "xinao_native_research_skill" in roles
    skill_row = next(
        row for row in manifest["source_inputs"] if row["role"] == "external_reality_research_skill"
    )
    assert skill_row["source_state"]["type"] == "directory"
    assert isinstance(skill_row["source_state"]["mode"], int)
    assert len(skill_row["source_state"]["sha256"]) == 64
    assert skill_row["source_state"]["entries"] == [
        {
            "path": "SKILL.md",
            "mode": (codex_home / "skills/research-external-reality/SKILL.md").stat().st_mode
            & 0o7777,
            "type": "file",
            "size_bytes": (codex_home / "skills/research-external-reality/SKILL.md").stat().st_size,
            "sha256": hashlib.sha256(
                (codex_home / "skills/research-external-reality/SKILL.md").read_bytes()
            ).hexdigest(),
        }
    ]


def test_subagent_profile_copies_only_the_disposable_trajectory(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    _write(repo / "tests/test_native_subagent_trajectory.py", "# test\n")
    _write(repo / "evals/native_subagent_trajectory/promptfooconfig.yaml", "tests: []\n")
    _write(repo / "evals/native_subagent_trajectory/fixture_template/AGENTS.md", "fixture\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(repo, output, "subagent")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective = Path(manifest["effective_root"])
    roles = {row["role"] for row in manifest["source_inputs"]}

    assert "native_subagent_trajectory_eval" in roles
    assert (effective / "evals/native_subagent_trajectory/promptfooconfig.yaml").exists()
    assert (effective / "tests/test_native_subagent_trajectory.py").exists()
    assert not (effective / "evals/codex_capability").exists()
    assert not (effective / "evals/thin_localization").exists()


def test_external_profile_copies_focused_suite_hot_kernel_and_skill(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    _write(repo / "tests/test_external_reality_research.py", "# test\n")
    _write(
        repo / "evals/external_reality_research/promptfooconfig.yaml",
        "tests: []\n",
    )
    codex_home = tmp_path / "codex-home"
    _write(codex_home / "AGENTS.md", "global external-reality kernel\n")
    _write(
        codex_home / "skills/research-external-reality/SKILL.md",
        "---\nname: research-external-reality\ndescription: fixture\n---\n",
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(repo, output, "external", codex_home=codex_home)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective = Path(manifest["effective_root"])
    roles = {row["role"] for row in manifest["source_inputs"]}

    assert "external_reality_research_eval" in roles
    assert "external_reality_research_tests" in roles
    assert "external_reality_research_skill" in roles
    assert "global_working_kernel" in roles
    assert (effective / "evals/external_reality_research/promptfooconfig.yaml").exists()
    assert (effective / "tests/test_external_reality_research.py").exists()
    assert not (effective / "evals/codex_capability").exists()
    assert not (effective / "evals/parent_frame_admission").exists()


def test_productivity_profile_copies_only_the_action_trajectory_and_hot_kernel(
    tmp_path: Path,
) -> None:
    repo = _fixture_repo(tmp_path)
    _write(repo / "tests/test_productive_action_trajectory.py", "# test\n")
    _write(
        repo / "evals/productive_action_trajectory/promptfooconfig.yaml",
        "tests: []\n",
    )
    _write(
        repo / "evals/productive_action_trajectory/fixture_template/consumer.py",
        "print('ok')\n",
    )
    codex_home = tmp_path / "codex-home"
    _write(codex_home / "AGENTS.md", "global productive-action kernel\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(
        repo,
        output,
        "productivity",
        codex_home=codex_home,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective = Path(manifest["effective_root"])
    roles = {row["role"] for row in manifest["source_inputs"]}

    assert "productive_action_trajectory_eval" in roles
    assert "productive_action_trajectory_tests" in roles
    assert "global_working_kernel" in roles
    assert (effective / "evals/productive_action_trajectory/promptfooconfig.yaml").exists()
    assert (effective / "tests/test_productive_action_trajectory.py").exists()
    assert not (effective / "evals/codex_capability").exists()
    assert not (effective / "evals/parent_frame_admission").exists()


def test_surface_profile_copies_only_natural_surface_suite_and_hot_kernel(
    tmp_path: Path,
) -> None:
    repo = _fixture_repo(tmp_path)
    _write(repo / "tests/test_parent_continuity_user_surface.py", "# test\n")
    _write(
        repo / "evals/parent_continuity_user_surface/promptfooconfig.yaml",
        "tests: []\n",
    )
    codex_home = tmp_path / "codex-home"
    _write(codex_home / "AGENTS.md", "global parent-continuity kernel\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(
        repo,
        output,
        "surface",
        codex_home=codex_home,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective = Path(manifest["effective_root"])
    roles = {row["role"] for row in manifest["source_inputs"]}

    assert "parent_continuity_user_surface_eval" in roles
    assert "parent_continuity_user_surface_tests" in roles
    assert "global_working_kernel" in roles
    assert (effective / "evals/parent_continuity_user_surface/promptfooconfig.yaml").exists()
    assert (effective / "tests/test_parent_continuity_user_surface.py").exists()
    assert not (effective / "evals/codex_capability").exists()
    assert not (effective / "evals/parent_frame_admission").exists()


def test_reconstitution_profile_copies_only_focused_suite_kernel_and_skill(
    tmp_path: Path,
) -> None:
    repo = _fixture_repo(tmp_path)
    _write(repo / "tests/test_recursive_frame_reconstitution.py", "# test\n")
    _write(
        repo / "evals/recursive_frame_reconstitution/promptfooconfig.yaml",
        "tests: []\n",
    )
    codex_home = tmp_path / "codex-home"
    _write(codex_home / "AGENTS.md", "global recursive-frame kernel\n")
    _write(
        codex_home / "skills/conduct-xinao-native-research/SKILL.md",
        "---\nname: conduct-xinao-native-research\ndescription: fixture\n---\n",
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    output = tmp_path / "run"
    output.mkdir()
    manifest_path = create_snapshot(
        repo,
        output,
        "reconstitution",
        codex_home=codex_home,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    effective = Path(manifest["effective_root"])
    roles = {row["role"] for row in manifest["source_inputs"]}

    assert "recursive_frame_reconstitution_eval" in roles
    assert "recursive_frame_reconstitution_tests" in roles
    assert "xinao_native_research_skill" in roles
    assert "global_working_kernel" in roles
    assert (effective / "evals/recursive_frame_reconstitution/promptfooconfig.yaml").exists()
    assert (effective / "tests/test_recursive_frame_reconstitution.py").exists()
    assert not (effective / "evals/parent_frame_admission").exists()
    assert not (effective / "evals/external_reality_research").exists()
