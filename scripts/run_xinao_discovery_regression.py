"""Prepare one worktree-local runtime and run the discovery suite without contention."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
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
FILE_ISOLATED_UNIT_DIRS = frozenset({"capability", "foundation"})
NODE_ISOLATED_TEST_PATHS = frozenset(
    {
        "xinao_discovery/tests/unit/foundation/test_f2_assertion_actuals_v2.py",
        "xinao_discovery/tests/unit/foundation/test_f2_assertions.py",
        "xinao_discovery/tests/unit/foundation/test_f2_compile.py",
        "xinao_discovery/tests/unit/foundation/test_f3_assertion_actuals_v2.py",
        "xinao_discovery/tests/unit/foundation/test_f4_production_checker.py",
        "xinao_discovery/tests/unit/foundation/test_research_factory.py",
        "xinao_discovery/tests/unit/foundation/test_research_weight_inputs.py",
    }
)

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
            "--group",
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
    shard_names = expand_test_shards(discover_test_shards())
    shard_manifest = {
        "schema_version": "xinao.discovery.regression_shards.v1",
        "strategy": "sequential_fresh_process_by_measured_crash_domain",
        "shards": shard_names,
    }
    shard_manifest["content_sha256"] = hashlib.sha256(
        json.dumps(
            shard_manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    print(json.dumps(shard_manifest, ensure_ascii=False, sort_keys=True))
    child_environment = os.environ.copy()
    child_environment[FULL_SUITE_LEASE_ENV] = FULL_SUITE_LEASE_VALUE
    results: list[dict[str, Any]] = []
    for shard_name in shard_names:
        started = time.monotonic()
        command = [
            str(PROJECT_PYTHON.resolve()),
            "-m",
            "pytest",
            shard_name,
            *pytest_args,
        ]
        returncode = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=child_environment,
            check=False,
        ).returncode
        result = {
            "shard": shard_name,
            "exit_code": returncode,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        results.append(result)
        print(
            json.dumps(
                {
                    "schema_version": "xinao.discovery.regression_shard_result.v1",
                    **result,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    failed = [result for result in results if result["exit_code"] != 0]
    summary = {
        "schema_version": "xinao.discovery.regression_summary.v1",
        "shard_manifest_sha256": shard_manifest["content_sha256"],
        "shard_count": len(results),
        "passed_shards": len(results) - len(failed),
        "failed_shards": failed,
        "status": "PASS" if not failed else "FAIL",
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if not failed:
        return 0
    first_code = int(failed[0]["exit_code"])
    return first_code if first_code in range(1, 7) else 3


def discover_test_shards(*, test_root: Path | None = None) -> list[Path]:
    """Cover the test tree once using natural packages and fresh processes."""

    root = PROJECT_ROOT / "tests" if test_root is None else test_root.resolve()
    if not root.is_dir():
        raise RegressionRunnerError(f"discovery test root is missing: {root}")
    shards: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_file():
            if entry.name.startswith("test_") and entry.suffix == ".py":
                shards.append(entry)
            continue
        if entry.name != "unit":
            if any(entry.rglob("test_*.py")):
                shards.append(entry)
            continue
        for unit_entry in sorted(entry.iterdir(), key=lambda path: path.name):
            if unit_entry.name.startswith(".") or unit_entry.name == "__pycache__":
                continue
            if unit_entry.is_dir():
                test_files = sorted(unit_entry.rglob("test_*.py"))
                if unit_entry.name in FILE_ISOLATED_UNIT_DIRS:
                    shards.extend(test_files)
                elif test_files:
                    shards.append(unit_entry)
            elif unit_entry.name.startswith("test_") and unit_entry.suffix == ".py":
                shards.append(unit_entry)
    if not shards:
        raise RegressionRunnerError(f"no discovery test shards found: {root}")
    return shards


def expand_test_shards(
    shards: Sequence[Path],
    *,
    repo_root: Path = REPO_ROOT,
    node_isolated_paths: frozenset[str] = NODE_ISOLATED_TEST_PATHS,
) -> list[str]:
    """Expand measured long-running files into function-level pytest node IDs."""

    root = repo_root.resolve()
    expanded: list[str] = []
    for shard in shards:
        resolved = shard.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as error:
            raise RegressionRunnerError(
                f"test shard escapes repository root: {resolved}"
            ) from error
        if relative not in node_isolated_paths:
            expanded.append(relative)
            continue
        parsed = ast.parse(resolved.read_text(encoding="utf-8"), filename=str(resolved))
        nodes: list[str] = []
        for statement in parsed.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if statement.name.startswith("test_"):
                    nodes.append(f"{relative}::{statement.name}")
                continue
            if not isinstance(statement, ast.ClassDef) or not statement.name.startswith(
                "Test"
            ):
                continue
            for member in statement.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    member.name.startswith("test_")
                ):
                    nodes.append(f"{relative}::{statement.name}::{member.name}")
        if not nodes:
            raise RegressionRunnerError(
                f"node-isolated test file exposes no static test nodes: {relative}"
            )
        expanded.extend(nodes)
    return expanded


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
