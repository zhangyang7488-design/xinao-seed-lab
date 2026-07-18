from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

from xinao.foundation import f4_current_evidence_verifier as verifier
from xinao.foundation.f4_production_checker import GROUPS, SCHEMA_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = PROJECT_ROOT.parent
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
CHECKER_SOURCE = PROJECT_ROOT / "src" / "xinao" / "foundation" / "f4_production_checker.py"


def _fresh() -> tuple[dict[str, object], bytes]:
    completed = subprocess.run(
        [
            str(PYTHON),
            "-X",
            "faulthandler",
            "-I",
            "-m",
            "xinao.foundation.f4_production_checker",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    raw = completed.stdout.strip()
    value = json.loads(raw.decode("utf-8"))
    assert isinstance(value, dict)
    return value, raw


def test_two_fresh_production_checker_runs_are_exact_and_pytest_free() -> None:
    first, first_raw = _fresh()
    second, second_raw = _fresh()

    assert first_raw == second_raw
    assert first == second
    assert first["schema_version"] == SCHEMA_VERSION
    assert first["status"] == "VERIFIED"
    assert first["check_count"] == first["verified_check_count"] == 17
    assert first["group_count"] == len(GROUPS) == 5
    assert first["groups"] == {key: list(value) for key, value in GROUPS.items()}
    assert first["pytest_loaded"] is False
    assert first["checker_source_sha256"] == hashlib.sha256(CHECKER_SOURCE.read_bytes()).hexdigest()


def test_production_checker_source_has_no_test_or_pytest_authority() -> None:
    tree = ast.parse(CHECKER_SOURCE.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    function_names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "pytest" not in imports
    assert not any(name.startswith("test_") for name in function_names)
    assert "test_research_factory" not in CHECKER_SOURCE.read_text(encoding="utf-8")


def test_current_verifier_runs_the_package_owned_checker() -> None:
    result = verifier.run_targeted_checker(timeout_seconds=180)

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["check_count"] == result["verified_check_count"] == 17
    assert result["pytest_loaded"] is False
