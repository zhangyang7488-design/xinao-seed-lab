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

GUARD_SCRIPT = (
    Path(__file__).resolve().parents[1] / "xinao_discovery" / "tests" / "conftest.py"
)
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
