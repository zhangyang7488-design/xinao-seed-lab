"""Contract and unit proofs for deterministic root pytest CI sharding."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from scripts.pytest_shard import (
    HASH_ALGORITHM,
    assign_shard,
    partition_nodeids,
    select_for_shard,
    validate_shard_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CODEQL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "codeql.yml"
SHARD_COUNT = 3


# ---------------------------------------------------------------------------
# Pure helper: fail-closed config, deterministic assignment, partition math
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "index"),
    [
        (0, 0),
        (-1, 0),
        (1, 1),
        (3, 3),
        (3, -1),
        (2, 5),
    ],
)
def test_invalid_shard_config_fails_closed(count: int, index: int) -> None:
    with pytest.raises(ValueError):
        validate_shard_config(count=count, index=index)


def test_bool_is_rejected_as_shard_config() -> None:
    with pytest.raises(ValueError):
        validate_shard_config(count=True, index=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        validate_shard_config(count=3, index=False)  # type: ignore[arg-type]


def test_assign_uses_explicit_stable_hash_not_builtin_hash() -> None:
    assert HASH_ALGORITHM == "sha256"
    # Built-in hash is salt-randomized; our assignment must ignore that.
    nodeid = "tests/test_example.py::test_a"
    a = assign_shard(nodeid, count=SHARD_COUNT)
    b = assign_shard(nodeid, count=SHARD_COUNT)
    assert a == b
    assert 0 <= a < SHARD_COUNT


def test_assignment_independent_of_pythonhashseed_subprocess() -> None:
    nodeid = "tests/test_repo_safety.py::test_ci_root_hygiene_job_is_single_platform_and_not_duplicated_in_pytest_matrix"
    script = (
        "from scripts.pytest_shard import assign_shard; "
        f"print(assign_shard({nodeid!r}, count={SHARD_COUNT}))"
    )
    results: list[str] = []
    for seed in ("0", "1", "42", "random"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        results.append(proc.stdout.strip())
    assert len(set(results)) == 1
    assert results[0] in {str(i) for i in range(SHARD_COUNT)}


def test_partition_union_equals_input_and_intersections_empty() -> None:
    # Representative large synthetic set (path-like node IDs, varied depth).
    nodeids = [
        f"tests/test_mod_{i // 50:03d}.py::test_case_{i:04d}[{param}]"
        for i, param in enumerate(f"p{j}" for j in range(500))
    ]
    nodeids.extend(f"tests/pkg/nested/test_x.py::TestCls::test_m{k}" for k in range(200))
    nodeids.extend(f"tests/test_edge.py::test_unicode_αβγ_{n}" for n in range(50))
    assert len(nodeids) == 750

    buckets = partition_nodeids(nodeids, count=SHARD_COUNT)
    assert len(buckets) == SHARD_COUNT
    recombined: list[str] = []
    for bucket in buckets:
        recombined.extend(bucket)
    assert sorted(recombined) == sorted(nodeids)
    assert len(recombined) == len(nodeids)

    for i in range(SHARD_COUNT):
        for j in range(i + 1, SHARD_COUNT):
            assert set(buckets[i]).isdisjoint(set(buckets[j]))

    # select_for_shard matches partition.
    for index in range(SHARD_COUNT):
        assert select_for_shard(nodeids, count=SHARD_COUNT, index=index) == buckets[index]


def test_duplicate_node_ids_rejected() -> None:
    nodeids = ["tests/a.py::test_one", "tests/a.py::test_two", "tests/a.py::test_one"]
    with pytest.raises(ValueError, match="duplicate node id"):
        partition_nodeids(nodeids, count=SHARD_COUNT)
    with pytest.raises(ValueError, match="duplicate node id"):
        select_for_shard(nodeids, count=SHARD_COUNT, index=0)


# ---------------------------------------------------------------------------
# Plugin integration: collection-time selection via pytest_deselected
# ---------------------------------------------------------------------------


def _write_demo_suite(tmp_path: Path, *, names: Sequence[str]) -> Path:
    body = "\n\n".join(f"def {name}():\n    assert True\n" for name in names)
    path = tmp_path / "test_demo_shard.py"
    path.write_text(body, encoding="utf-8")
    return path


def _run_pytest_in(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Repo root on PYTHONPATH so -p scripts.pytest_shard resolves.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), env["PYTHONPATH"]] if env.get("PYTHONPATH") else [str(REPO_ROOT)]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_plugin_deselects_other_shards_and_keeps_assigned(tmp_path: Path) -> None:
    names = [f"test_{letter}" for letter in "abcdef"]
    _write_demo_suite(tmp_path, names=names)
    collect = _run_pytest_in(tmp_path, "--collect-only", "-q")
    assert collect.returncode == 0, collect.stdout + collect.stderr
    nodeids = [
        line.strip()
        for line in collect.stdout.splitlines()
        if line.strip().startswith("test_demo_shard.py::")
    ]
    assert len(nodeids) == 6
    expected = select_for_shard(nodeids, count=SHARD_COUNT, index=0)
    assert expected, "fixture suite must hit shard 0 for this proof"

    result = _run_pytest_in(
        tmp_path,
        "-p",
        "scripts.pytest_shard",
        "--shard-count",
        str(SHARD_COUNT),
        "--shard-index",
        "0",
        "-q",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    # Summary: N passed, M deselected
    assert f"{len(expected)} passed" in combined
    deselected = 6 - len(expected)
    if deselected:
        assert f"{deselected} deselected" in combined


def test_plugin_empty_shard_fails_closed(tmp_path: Path) -> None:
    _write_demo_suite(tmp_path, names=["test_only"])
    collect = _run_pytest_in(tmp_path, "--collect-only", "-q")
    assert collect.returncode == 0, collect.stdout + collect.stderr
    nodeids = [
        line.strip()
        for line in collect.stdout.splitlines()
        if line.strip().startswith("test_demo_shard.py::")
    ]
    assert len(nodeids) == 1
    assigned = assign_shard(nodeids[0], count=50)
    empty_index = 0 if assigned != 0 else 1
    result = _run_pytest_in(
        tmp_path,
        "-p",
        "scripts.pytest_shard",
        "--shard-count",
        "50",
        "--shard-index",
        str(empty_index),
        "-q",
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "zero tests" in combined or "empty shard" in combined


def test_plugin_invalid_index_fails_at_configure(tmp_path: Path) -> None:
    _write_demo_suite(tmp_path, names=["test_x"])
    result = _run_pytest_in(
        tmp_path,
        "-p",
        "scripts.pytest_shard",
        "--shard-count",
        "3",
        "--shard-index",
        "3",
        "-q",
    )
    assert result.returncode != 0


def test_plugin_inactive_without_options_runs_all(tmp_path: Path) -> None:
    _write_demo_suite(tmp_path, names=["test_a", "test_b"])
    # Load plugin but omit shard flags → no filtering (local default path).
    result = _run_pytest_in(tmp_path, "-p", "scripts.pytest_shard", "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# Real root collection: every shard non-empty; coverage partition holds
# ---------------------------------------------------------------------------


def _collect_root_nodeids() -> list[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    nodeids: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("=") or " tests collected" in line:
            continue
        if line.startswith("tests/") or line.startswith("tests\\"):
            nodeids.append(line.replace("\\", "/"))
        elif "::" in line and not line.startswith("ERROR"):
            # Rare absolute or alternate forms
            nodeids.append(line.replace("\\", "/"))
    if not nodeids:
        # Fallback: parse summary only is insufficient; fail clearly.
        raise AssertionError(
            "root --collect-only produced no node IDs; stdout tail:\n"
            + "\n".join(proc.stdout.splitlines()[-20:])
        )
    return nodeids


def test_real_root_collection_shards_are_nonempty_and_partition() -> None:
    nodeids = _collect_root_nodeids()
    assert len(nodeids) >= 500, f"unexpectedly small root collection: {len(nodeids)}"
    # Duplicates must not appear in real collection (helper would raise).
    buckets = partition_nodeids(nodeids, count=SHARD_COUNT)
    for index, bucket in enumerate(buckets):
        assert bucket, f"shard {index} is empty for real root collection"
    recombined = [n for b in buckets for n in b]
    assert sorted(recombined) == sorted(nodeids)
    for i in range(SHARD_COUNT):
        for j in range(i + 1, SHARD_COUNT):
            assert set(buckets[i]).isdisjoint(set(buckets[j]))
    # Distribution should not collapse wall-time savings via extreme skew.
    sizes = [len(b) for b in buckets]
    assert max(sizes) / max(min(sizes), 1) < 2.0, f"severe shard skew: {sizes}"


# ---------------------------------------------------------------------------
# Workflow contract: full OS×shard matrix, helper invocation, no shortcuts
# ---------------------------------------------------------------------------


def _load_ci() -> dict:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_defines_full_os_shard_matrix() -> None:
    workflow = _load_ci()
    verify = workflow["jobs"]["verify"]
    assert verify["strategy"]["fail-fast"] is False
    assert verify["needs"] == "root-hygiene" or verify["needs"] == ["root-hygiene"]
    include = verify["strategy"]["matrix"]["include"]
    expected = {
        ("ubuntu-latest", "3.12", 0, 3),
        ("ubuntu-latest", "3.12", 1, 3),
        ("ubuntu-latest", "3.12", 2, 3),
        ("windows-latest", "3.11", 0, 3),
        ("windows-latest", "3.11", 1, 3),
        ("windows-latest", "3.11", 2, 3),
    }
    actual = {
        (
            entry["os"],
            str(entry["python-version"]),
            int(entry["shard"]),
            int(entry["shard_count"]),
        )
        for entry in include
    }
    assert actual == expected
    assert len(include) == 6


def test_every_shard_job_invokes_helper_with_matrix_and_unique_basetemp() -> None:
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    workflow = _load_ci()
    verify = workflow["jobs"]["verify"]
    run_steps = [
        step["run"]
        for step in verify["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), str) and "pytest" in step["run"]
    ]
    assert len(run_steps) == 1
    run = run_steps[0]
    assert "-p scripts.pytest_shard" in run
    assert "--shard-count ${{ matrix.shard_count }}" in run
    assert "--shard-index ${{ matrix.shard }}" in run
    assert '--basetemp "${{ runner.temp }}/pytest-shard-${{ matrix.shard }}"' in run
    # Unique basetemp includes shard index; not a shared fixed path across shards.
    assert "pytest-shard-${{ matrix.shard }}" in run
    assert "continue-on-error" not in workflow_text
    assert "paths-filter" not in workflow_text
    assert "dorny/paths-filter" not in workflow_text
    assert "pytest-xdist" not in workflow_text
    assert re.search(r"(?:^|\s)-n\s", run) is None
    # Root verify must not shrink the cone via path filters or explicit test paths.
    assert re.search(r"pytest\s+-q\s+-p\s+scripts\.pytest_shard", run)
    assert "tests/" not in run
    assert "tests\\" not in run


def test_project_verify_and_codeql_surfaces_remain() -> None:
    workflow = _load_ci()
    assert "project-verify" in workflow["jobs"]
    project = workflow["jobs"]["project-verify"]
    projects = {entry["project"] for entry in project["strategy"]["matrix"]["include"]}
    assert "dual-brain-coordination" in projects
    assert "xinao-market-lab" in projects
    assert "xinao-discovery" in projects
    assert CODEQL_WORKFLOW.is_file()
    codeql = CODEQL_WORKFLOW.read_text(encoding="utf-8")
    assert "github/codeql-action/analyze@v3" in codeql
    assert "name: CodeQL" in codeql


def test_local_non_sharded_pytest_invocation_unchanged_in_workflow_contract() -> None:
    """Root CI always uses the plugin; local default path must not force shards."""
    # Helper defaults: without options, validate is not applied; plugin no-ops.
    # Document that README/scripts do not inject shard flags into plain pytest.
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    # Plain local pytest path (if mentioned) must not hard-require shards.
    if "uv run pytest -q" in readme:
        # Allow mention, but not a forced --shard-count default instruction.
        for line in readme.splitlines():
            if "uv run pytest -q" in line and "--shard-count" in line:
                pytest.fail(f"local default pytest path must not force sharding: {line}")
