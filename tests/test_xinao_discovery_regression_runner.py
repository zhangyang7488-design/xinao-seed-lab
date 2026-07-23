from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_xinao_discovery_regression.py"
SPEC = importlib.util.spec_from_file_location("run_xinao_discovery_regression", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)

GUARD_SCRIPT = Path(__file__).resolve().parents[1] / "xinao_discovery" / "tests" / "conftest.py"
GUARD_SPEC = importlib.util.spec_from_file_location("xinao_discovery_test_guard", GUARD_SCRIPT)
assert GUARD_SPEC is not None and GUARD_SPEC.loader is not None
guard = importlib.util.module_from_spec(GUARD_SPEC)
GUARD_SPEC.loader.exec_module(guard)


class FakeProcess:
    def __init__(self, pid: int, command: list[str], created: float = 1.0) -> None:
        self.pid = pid
        self._command = command
        self._created = created

    def cmdline(self) -> list[str]:
        return self._command

    def create_time(self) -> float:
        return self._created


def test_full_suite_command_detection_is_exact_enough() -> None:
    assert (
        subject._is_discovery_full_suite_command(
            ["python.exe", "-m", "pytest", "xinao_discovery/tests", "-q"]
        )
        is True
    )
    assert (
        subject._is_discovery_full_suite_command(
            ["python.exe", "-m", "pytest", "xinao_discovery/tests/unit/test_one.py"]
        )
        is False
    )
    assert (
        subject._is_discovery_full_suite_command(
            ["python.exe", "-m", "pytest", "tests/test_repo_safety.py"]
        )
        is False
    )


def test_raw_full_suite_requires_runner_lease() -> None:
    assert subject.FULL_SUITE_LEASE_ENV == guard.FULL_SUITE_LEASE_ENV
    assert subject.FULL_SUITE_LEASE_VALUE == guard.FULL_SUITE_LEASE_VALUE

    with pytest.raises(pytest.UsageError, match="requires the serialized runner"):
        guard.require_safe_full_suite(
            ["xinao_discovery/tests"],
            environment={},
        )

    guard.require_safe_full_suite(
        ["xinao_discovery/tests"],
        environment={
            subject.FULL_SUITE_LEASE_ENV: subject.FULL_SUITE_LEASE_VALUE,
        },
    )
    guard.require_safe_full_suite(
        ["xinao_discovery/tests/unit/capability/test_g4_family_batch.py"],
        environment={},
    )


def test_competing_suite_inventory_ignores_unrelated_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = SimpleNamespace(pid=100, parent=lambda: None)
    monkeypatch.setattr(subject.os, "getpid", lambda: 100)
    monkeypatch.setattr(subject.psutil, "Process", lambda _pid: current)
    processes = [
        FakeProcess(101, ["python.exe", "-m", "pytest", "tests"]),
        FakeProcess(
            102,
            ["python.exe", "-m", "pytest", "xinao_discovery/tests", "-q"],
            created=2.0,
        ),
    ]

    rows = subject.find_competing_full_suites(processes)

    assert rows == [
        {
            "pid": 102,
            "create_time": 2.0,
            "command": [
                "python.exe",
                "-m",
                "pytest",
                "xinao_discovery/tests",
                "-q",
            ],
        }
    ]


def test_runtime_receipt_requires_carrier_local_interpreters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subject, "ROOT_PYTHON", Path("missing-root-python.exe"))

    with pytest.raises(subject.RegressionRunnerError, match="carrier interpreter is missing"):
        subject.build_carrier_runtime_receipt()


def test_carrier_sync_uses_root_extra_and_project_dependency_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        subject,
        "_run_checked",
        lambda command, *, cwd: calls.append((list(command), cwd)),
    )

    subject.sync_carrier_runtime(uv_executable="uv-test")

    assert calls == [
        (
            [
                "uv-test",
                "sync",
                "--frozen",
                "--extra",
                "dev",
                "--extra",
                "workflow",
            ],
            subject.REPO_ROOT,
        ),
        (
            [
                "uv-test",
                "sync",
                "--project",
                str(subject.PROJECT_ROOT),
                "--frozen",
                "--group",
                "dev",
                "--extra",
                "g4-bootstrap",
            ],
            subject.REPO_ROOT,
        ),
    ]


def test_competitor_holds_before_sync_or_runtime_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subject,
        "find_competing_full_suites",
        lambda: [{"pid": 102, "create_time": 2.0, "command": ["pytest"]}],
    )
    monkeypatch.setattr(subject, "sync_carrier_runtime", lambda: calls.append("sync"))
    monkeypatch.setattr(
        subject,
        "build_carrier_runtime_receipt",
        lambda: calls.append("receipt"),
    )

    with pytest.raises(
        subject.RegressionRunnerError,
        match="competing discovery full suite is active",
    ):
        subject.execute_regression(
            pytest_args=["-q"],
            lock_path=tmp_path / "suite.lock",
        )

    assert calls == []


def test_one_lease_covers_sync_receipt_and_pytest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(subject, "find_competing_full_suites", lambda: [])
    monkeypatch.setattr(subject, "sync_carrier_runtime", lambda: calls.append("sync"))
    monkeypatch.setattr(
        subject,
        "build_carrier_runtime_receipt",
        lambda: calls.append("receipt") or {"ready": True},
    )
    monkeypatch.setattr(
        subject,
        "_run_full_suite",
        lambda *, pytest_args: calls.append(f"pytest:{list(pytest_args)}") or 0,
    )

    result = subject.execute_regression(
        pytest_args=["-q"],
        lock_path=tmp_path / "suite.lock",
    )

    assert result == 0
    assert calls == ["sync", "receipt", "pytest:['-q']"]
    assert '"ready": true' in capsys.readouterr().out


def test_test_shards_cover_natural_packages_once(tmp_path: Path) -> None:
    test_root = tmp_path / "tests"
    paths = [
        test_root / "contract" / "test_contract.py",
        test_root / "property" / "test_property.py",
        test_root / "unit" / "foundation" / "test_foundation.py",
        test_root / "unit" / "test_direct.py",
        test_root / "fixtures" / "data.json",
        test_root / "conftest.py",
        test_root / "__pycache__" / "ignored.pyc",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    shards = subject.discover_test_shards(test_root=test_root)

    assert shards == [
        test_root / "contract",
        test_root / "property",
        test_root / "unit" / "foundation" / "test_foundation.py",
        test_root / "unit" / "test_direct.py",
    ]


def test_sharded_suite_runs_fresh_processes_and_aggregates_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shard_a = subject.REPO_ROOT / "xinao_discovery" / "tests" / "contract"
    shard_b = subject.REPO_ROOT / "xinao_discovery" / "tests" / "unit" / "foundation"
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []
    returncodes = iter([0, 1])
    monkeypatch.setattr(subject, "discover_test_shards", lambda: [shard_a, shard_b])
    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda command, *, cwd, env, check: (
            commands.append(list(command))
            or environments.append(dict(env))
            or SimpleNamespace(returncode=next(returncodes))
        ),
    )

    result = subject._run_full_suite(pytest_args=["-q"])

    assert result == 1
    assert [command[-2:] for command in commands] == [
        ["xinao_discovery/tests/contract", "-q"],
        ["xinao_discovery/tests/unit/foundation", "-q"],
    ]
    assert all(
        environment[subject.FULL_SUITE_LEASE_ENV] == subject.FULL_SUITE_LEASE_VALUE
        for environment in environments
    )
    output = capsys.readouterr().out
    assert '"shard_count": 2' in output
    assert '"passed_shards": 1' in output
    assert '"status": "FAIL"' in output
