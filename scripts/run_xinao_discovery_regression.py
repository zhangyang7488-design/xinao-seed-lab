"""Prepare one worktree-local runtime and run the discovery suite without contention."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import portalocker
import psutil

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT / "xinao_discovery"
ROOT_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
LOCK_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\test_leases\xinao_discovery_full_regression.lock"
)
FULL_SUITE_LEASE_ENV = "XINAO_DISCOVERY_FULL_REGRESSION_LEASE"
FULL_SUITE_LEASE_VALUE = "runner-v1"

ROOT_IMPORTS = (
    "apsw",
    "jsonschema",
    "mlflow",
    "opentelemetry",
    "pydantic",
    "psutil",
    "rfc8785",
    "temporalio",
    "uuid6",
)
PROJECT_IMPORTS = (
    "hypothesis",
    "pydantic",
    "rfc8785",
    "uuid6",
)


class RegressionRunnerError(RuntimeError):
    """Carrier preparation or heavy-suite admission failed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_checked(command: Sequence[str], *, cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode != 0:
        raise RegressionRunnerError(
            f"command failed with exit {completed.returncode}: {list(command)}"
        )


def sync_carrier_runtime(*, uv_executable: str = "uv") -> None:
    """Materialize both project-root environments from the current lock."""

    _run_checked(
        [
            uv_executable,
            "sync",
            "--frozen",
            "--extra",
            "dev",
            "--extra",
            "workflow",
        ],
        cwd=REPO_ROOT,
    )
    _run_checked(
        [
            uv_executable,
            "sync",
            "--project",
            str(PROJECT_ROOT),
            "--frozen",
            "--extra",
            "dev",
            "--extra",
            "g4-bootstrap",
        ],
        cwd=REPO_ROOT,
    )


def _probe_python(python: Path, imports: Sequence[str]) -> dict[str, Any]:
    resolved = python.resolve()
    if not resolved.is_file():
        raise RegressionRunnerError(f"carrier interpreter is missing: {resolved}")
    script = (
        "import importlib,json,platform,sys;"
        f"names={json.dumps(list(imports))};"
        "[importlib.import_module(name) for name in names];"
        "print(json.dumps({'implementation':platform.python_implementation(),"
        "'version':platform.python_version(),'prefix':sys.prefix,"
        "'imports':names},sort_keys=True))"
    )
    completed = subprocess.run(
        [str(resolved), "-I", "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise RegressionRunnerError(
            f"carrier interpreter probe failed: {resolved}: {completed.stderr.strip()}"
        )
    try:
        identity = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RegressionRunnerError(f"invalid interpreter probe output: {resolved}") from exc
    expected_prefix = resolved.parents[1]
    if Path(identity["prefix"]).resolve() != expected_prefix:
        raise RegressionRunnerError(
            f"interpreter prefix escapes carrier environment: {identity['prefix']}"
        )
    return {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        **identity,
    }


def build_carrier_runtime_receipt() -> dict[str, Any]:
    """Prove the current code root, lock, and both interpreter identities agree."""

    if not (REPO_ROOT / ".git").exists():
        raise RegressionRunnerError(f"repository identity is missing: {REPO_ROOT}")
    lock_path = REPO_ROOT / "uv.lock"
    if not lock_path.is_file():
        raise RegressionRunnerError(f"root lock is missing: {lock_path}")
    body: dict[str, Any] = {
        "schema_version": "xinao.discovery.carrier_runtime_preflight.v1",
        "repo_root": str(REPO_ROOT),
        "project_root": str(PROJECT_ROOT),
        "uv_lock_sha256": _sha256_file(lock_path),
        "root_runtime": _probe_python(ROOT_PYTHON, ROOT_IMPORTS),
        "project_runtime": _probe_python(PROJECT_PYTHON, PROJECT_IMPORTS),
        "carrier_local_runtime": True,
        "cross_worktree_environment_reuse": False,
        "ready": True,
    }
    body["content_sha256"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return body


def _is_discovery_full_suite_command(command: Sequence[str]) -> bool:
    normalized = [token.replace("\\", "/").rstrip("/").lower() for token in command]
    return any("pytest" in token for token in normalized) and (
        "xinao_discovery/tests" in normalized
    )


def find_competing_full_suites(
    processes: Iterable[psutil.Process] | None = None,
) -> list[dict[str, Any]]:
    """Return live discovery suites other than this runner and its ancestors."""

    own_lineage = {os.getpid()}
    current = psutil.Process(os.getpid())
    while current.parent() is not None:
        current = current.parent()
        own_lineage.add(current.pid)
    rows: list[dict[str, Any]] = []
    source = processes if processes is not None else psutil.process_iter()
    for process in source:
        try:
            if process.pid in own_lineage:
                continue
            command = process.cmdline()
            if not _is_discovery_full_suite_command(command):
                continue
            rows.append(
                {
                    "pid": process.pid,
                    "create_time": process.create_time(),
                    "command": command,
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return sorted(rows, key=lambda row: row["pid"])


def _run_full_suite(*, pytest_args: Sequence[str]) -> int:
    command = [
        str(PROJECT_PYTHON.resolve()),
        "-m",
        "pytest",
        "xinao_discovery/tests",
        *pytest_args,
    ]
    child_environment = os.environ.copy()
    child_environment[FULL_SUITE_LEASE_ENV] = FULL_SUITE_LEASE_VALUE
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=child_environment,
        check=False,
    ).returncode


def execute_regression(
    *,
    pytest_args: Sequence[str],
    sync: bool = True,
    preflight_only: bool = False,
    lock_path: Path = LOCK_PATH,
) -> int:
    """Hold one lease across admission, runtime preparation, and pytest."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with portalocker.Lock(
            str(lock_path),
            mode="a+b",
            timeout=0,
            flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
        ):
            competitors = find_competing_full_suites()
            if competitors:
                raise RegressionRunnerError(
                    "competing discovery full suite is active: "
                    + json.dumps(competitors, ensure_ascii=False, sort_keys=True)
                )
            if sync:
                sync_carrier_runtime()
            receipt = build_carrier_runtime_receipt()
            print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
            if preflight_only:
                return 0
            return _run_full_suite(pytest_args=pytest_args)
    except portalocker.exceptions.LockException as exc:
        raise RegressionRunnerError(
            f"discovery full-suite lease is already held: {lock_path}"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Sync and verify the carrier without running pytest.",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Diagnostic only: verify already-materialized environments.",
    )
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="Argument forwarded to pytest after xinao_discovery/tests.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return execute_regression(
            pytest_args=args.pytest_arg or ["-q"],
            sync=not args.skip_sync,
            preflight_only=args.preflight_only,
        )
    except RegressionRunnerError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "xinao.discovery.regression_runner_failure.v1",
                    "status": "HOLD",
                    "reason": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
