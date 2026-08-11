from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from evals.situation_snapshot_lab.runtime_observation import (
    RUNTIME_OBSERVATION_VERSION,
    RuntimeObservation,
    RuntimeObservationError,
    collect_runtime_observation,
)


def _payload() -> dict[str, object]:
    return collect_runtime_observation().to_dict()


def _candidate(payload: dict[str, object], path: Path) -> dict[str, object]:
    observed = payload["observed"]
    assert isinstance(observed, dict)
    candidates = observed["file_candidates"]
    assert isinstance(candidates, list)
    for row in candidates:
        assert isinstance(row, dict)
        if os.path.normcase(str(row["path"])) == os.path.normcase(str(path.absolute())):
            return row
    raise AssertionError(f"candidate was not observed: {path}")


def _unknown_fields(payload: dict[str, object]) -> set[str]:
    unknown = payload["unknown"]
    assert isinstance(unknown, list)
    return {str(row["field"]) for row in unknown if isinstance(row, dict)}


def _git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_observes_only_actual_cwd_process_and_allowlisted_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.chdir(actual)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-observed")
    monkeypatch.setenv("UNRELATED_RUNTIME_VALUE", "must-not-appear")

    payload = _payload()
    observed = payload["observed"]
    assert isinstance(observed, dict)

    assert Path(str(observed["cwd"])) == actual.absolute()
    process = observed["observer_process"]
    assert isinstance(process, dict)
    assert process["pid"] == os.getpid()
    assert process["parent_pid"] == os.getppid()
    assert Path(str(process["executable"])).is_absolute()
    assert observed["environment"] == {
        "CODEX_HOME": str(codex_home),
        "CODEX_THREAD_ID": "thread-observed",
    }
    assert "must-not-appear" not in json.dumps(payload, sort_keys=True)


def test_global_and_ancestor_candidates_include_identity_and_symlink_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    global_config = codex_home / "config.toml"
    global_config.write_bytes(b"model = 'declared-only'\n")
    root = tmp_path / "workspace"
    nested = root / "child"
    nested.mkdir(parents=True)
    ancestor_hooks = root / ".codex" / "hooks.json"
    ancestor_hooks.parent.mkdir()
    ancestor_hooks.write_bytes(b'{"hooks": {}}\n')
    target = tmp_path / "real-agents.md"
    target.write_bytes(b"linked instructions\n")
    linked_agents = nested / "AGENTS.md"
    broken_agents = root / "AGENTS.md"
    try:
        linked_agents.symlink_to(target)
        broken_agents.symlink_to(root / "missing-agents-target.md")
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    monkeypatch.chdir(nested)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    payload = _payload()

    global_row = _candidate(payload, global_config)
    assert global_row["scope"] == "global"
    assert global_row["kind"] == "config"
    assert global_row["exists"] is True
    assert global_row["sha256"] == hashlib.sha256(global_config.read_bytes()).hexdigest()
    assert global_row["bytes"] == len(global_config.read_bytes())

    hooks_row = _candidate(payload, ancestor_hooks)
    assert hooks_row["scope"] == "ancestor"
    assert hooks_row["kind"] == "hooks"
    assert hooks_row["resolved_target"] == str(ancestor_hooks.resolve())

    link_row = _candidate(payload, linked_agents)
    assert link_row["symlink"] is True
    assert link_row["resolved_target"] == str(target.resolve())
    assert link_row["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert link_row["bytes"] == len(target.read_bytes())
    assert link_row["target_exists"] is True
    assert link_row["path_redirected"] is True
    broken_row = _candidate(payload, broken_agents)
    assert broken_row["exists"] is True
    assert broken_row["symlink"] is True
    assert broken_row["target_exists"] is False
    assert broken_row["sha256"] is None
    assert "linked instructions" not in json.dumps(payload, sort_keys=True)


def test_non_git_and_current_permission_enforcement_remain_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    payload = _payload()
    observed = payload["observed"]
    assert isinstance(observed, dict)

    assert observed["git"] is None
    assert "permissions" not in observed
    assert {
        "observed.git",
        "observed.permissions.approval_policy",
        "observed.permissions.filesystem_access",
        "observed.permissions.sandbox_mode",
    }.issubset(_unknown_fields(payload))


def test_symlink_retarget_during_final_target_probe_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    linked_agents = work / "AGENTS.md"
    target_b = tmp_path / "target-b.md"
    target_b.write_bytes(b"target b\n")
    try:
        linked_agents.symlink_to(tmp_path / "missing-a.md")
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")
    monkeypatch.chdir(work)
    original_stat = Path.stat
    retargeted = False

    def racing_stat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal retargeted
        if path == linked_agents and not retargeted:
            linked_agents.unlink()
            linked_agents.symlink_to(target_b)
            retargeted = True
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", racing_stat)
    payload = _payload()
    row = _candidate(payload, linked_agents)

    assert retargeted is True
    assert row["capture_stable"] is False
    assert row["resolved_target"] is None
    assert row["target_exists"] is None
    assert any(
        unknown_row.get("field", "").startswith("observed.file_candidates[")
        and unknown_row.get("reason") == "path_or_target_changed_during_probe"
        for unknown_row in payload["unknown"]
        if isinstance(unknown_row, dict)
    )


def test_declared_invocation_never_overrides_observed_or_promotes_model_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = tmp_path / "actual"
    claimed = tmp_path / "claimed"
    actual.mkdir()
    claimed.mkdir()
    monkeypatch.chdir(actual)

    observation = collect_runtime_observation(
        declared_invocation={
            "cwd": str(claimed),
            "provider": "candidate-provider",
            "sandbox_mode": "read-only",
            "write_capability": False,
            "model_output": {
                "observed": {"sandbox_mode": "unbounded", "cwd": str(claimed)}
            },
        }
    )
    payload = observation.to_dict()
    observed = payload["observed"]
    declared = payload["declared"]
    assert isinstance(observed, dict)
    assert isinstance(declared, dict)

    invocation = declared["invocation"]
    assert isinstance(invocation, dict)
    assert Path(str(observed["cwd"])) == actual.absolute()
    assert invocation["cwd"] == str(claimed)
    assert invocation["sandbox_mode"] == "read-only"
    assert "permissions" not in observed
    assert "model_output" not in invocation
    assert "unbounded" not in json.dumps(payload, sort_keys=True)
    assert "observed.permissions.sandbox_mode" in _unknown_fields(payload)


def test_environment_file_and_declared_secrets_are_never_emitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-test-secret-material-123456"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        f'api_key = "{secret}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("AUTH_TOKEN", secret)
    monkeypatch.setenv("CODEX_THREAD_ID", secret)

    payload = collect_runtime_observation(
        declared_invocation={
            "provider": "candidate-provider",
            "model": f"prefix {secret}",
            "api_key": secret,
            "prompt": f"repeat {secret}",
            "result_identity": {"token": secret},
        }
    ).to_dict()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    declared = payload["declared"]
    assert isinstance(declared, dict)

    assert secret not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "AUTH_TOKEN" not in serialized
    assert "api_key" not in serialized
    assert "prompt" not in serialized
    assert declared["invocation"] == {"provider": "candidate-provider"}
    assert "observed.environment.CODEX_THREAD_ID" in _unknown_fields(payload)
    config_row = _candidate(payload, codex_home / "config.toml")
    assert config_row["sha256"] == hashlib.sha256(
        (codex_home / "config.toml").read_bytes()
    ).hexdigest()


def test_facts_hash_excludes_capture_time_but_detects_file_hash_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    agents = codex_home / "AGENTS.md"
    agents.write_bytes(b"first fact\n")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    first = collect_runtime_observation()
    first_payload = first.to_dict()
    second = collect_runtime_observation()

    assert first.facts_sha256 == second.facts_sha256
    differently_declared = collect_runtime_observation(
        declared_invocation={"provider": "different-caller-assertion"}
    )
    assert differently_declared.facts_sha256 == first.facts_sha256
    agents.write_bytes(b"other fact\n")
    drifted = collect_runtime_observation()
    assert drifted.facts_sha256 != first.facts_sha256
    assert _candidate(drifted.to_dict(), agents)["sha256"] == hashlib.sha256(
        b"other fact\n"
    ).hexdigest()

    digest_body = {
        "schema_version": RUNTIME_OBSERVATION_VERSION,
        "observed": first_payload["observed"],
    }
    expected = hashlib.sha256(
        json.dumps(
            digest_body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert first.facts_sha256 == expected

    with pytest.raises(RuntimeObservationError, match="local collector"):
        RuntimeObservation()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_git_root_head_branch_worktree_common_dir_and_dirty_are_observed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "--quiet", cwd=repo)
    tracked = repo / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=repo)
    _git(
        "-c",
        "user.name=Runtime Observation Test",
        "-c",
        "user.email=runtime-observation@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "initial",
        cwd=repo,
    )
    expected_head = _git("rev-parse", "HEAD", cwd=repo).stdout.decode().strip()
    nested = repo / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong-git-dir"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(repo))

    clean = _payload()
    observed = clean["observed"]
    assert isinstance(observed, dict)
    git = observed["git"]
    assert isinstance(git, dict)
    assert Path(str(git["root"])).resolve() == repo.resolve()
    assert Path(str(git["worktree"])).resolve() == repo.resolve()
    assert Path(str(git["common_dir"])).resolve() == (repo / ".git").resolve()
    assert git["head"] == expected_head
    assert isinstance(git["branch"], str) and git["branch"]
    assert git["linked_worktree"] is False
    assert git["detached_head"] is False
    assert git["dirty"] is False
    assert git["dirty_fingerprint_complete"] is True
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_CEILING_DIRECTORIES")

    injected_ignore = tmp_path / "injected-ignore.txt"
    injected_ignore.write_text("ghost.txt\n", encoding="utf-8")
    ghost = repo / "ghost.txt"
    ghost.write_text("must remain visible to the neutral probe\n", encoding="utf-8")
    helper_marker = tmp_path / "fsmonitor-secret-marker.txt"
    fsmonitor_helper = tmp_path / "fsmonitor.cmd"
    fsmonitor_helper.write_text(
        f"@echo off\r\necho %OPENAI_API_KEY%>{helper_marker}\r\necho/\r\n",
        encoding="utf-8",
    )
    _git("config", "core.fsmonitor", str(fsmonitor_helper), cwd=repo)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-secret-sentinel")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(injected_ignore))

    neutral = _payload()
    neutral_observed = neutral["observed"]
    assert isinstance(neutral_observed, dict)
    neutral_git = neutral_observed["git"]
    assert isinstance(neutral_git, dict)
    assert neutral_git["dirty"] is True
    assert not helper_marker.exists()
    ghost.unlink()
    monkeypatch.delenv("GIT_CONFIG_COUNT")
    monkeypatch.delenv("GIT_CONFIG_KEY_0")
    monkeypatch.delenv("GIT_CONFIG_VALUE_0")

    tracked.write_text("dirty\n", encoding="utf-8")
    dirty = _payload()
    dirty_observed = dirty["observed"]
    assert isinstance(dirty_observed, dict)
    dirty_git = dirty_observed["git"]
    assert isinstance(dirty_git, dict)
    assert dirty_git["dirty"] is True
    assert dirty["facts_sha256"] != clean["facts_sha256"]

    tracked.write_text("different dirty bytes\n", encoding="utf-8")
    differently_dirty = _payload()
    differently_dirty_observed = differently_dirty["observed"]
    assert isinstance(differently_dirty_observed, dict)
    differently_dirty_git = differently_dirty_observed["git"]
    assert isinstance(differently_dirty_git, dict)
    assert differently_dirty_git["porcelain_status_sha256"] == dirty_git[
        "porcelain_status_sha256"
    ]
    assert differently_dirty_git["dirty_fingerprint_sha256"] != dirty_git[
        "dirty_fingerprint_sha256"
    ]
    assert differently_dirty["facts_sha256"] != dirty["facts_sha256"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_linked_worktree_common_dir_and_git_dir_are_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "main"
    linked = tmp_path / "linked"
    repo.mkdir()
    _git("init", "--quiet", cwd=repo)
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=repo)
    _git(
        "-c",
        "user.name=Runtime Observation Test",
        "-c",
        "user.email=runtime-observation@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "initial",
        cwd=repo,
    )
    _git("worktree", "add", "--quiet", "--detach", str(linked), "HEAD", cwd=repo)
    monkeypatch.chdir(linked)
    monkeypatch.delenv("CODEX_HOME", raising=False)

    payload = _payload()
    observed = payload["observed"]
    assert isinstance(observed, dict)
    git = observed["git"]
    assert isinstance(git, dict)
    assert Path(str(git["worktree"])).resolve() == linked.resolve()
    assert Path(str(git["common_dir"])).resolve() == (repo / ".git").resolve()
    assert Path(str(git["git_dir"])).resolve() != Path(str(git["common_dir"])).resolve()
    assert git["linked_worktree"] is True
    assert git["detached_head"] is True
    assert git["snapshot_stable"] is True


def test_observation_is_candidate_only_and_detached_views_do_not_mutate_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    observation = collect_runtime_observation()
    first = observation.to_dict()
    observed = first["observed"]
    assert isinstance(observed, dict)
    observed["cwd"] = "fabricated"

    second = observation.to_dict()
    assert second["observed"] != first["observed"]
    assert second["authority"] is False
    assert second["completion_claim_allowed"] is False
