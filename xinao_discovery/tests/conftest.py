from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

FULL_SUITE_LEASE_ENV = "XINAO_DISCOVERY_FULL_REGRESSION_LEASE"
FULL_SUITE_LEASE_VALUE = "runner-v1"
TEST_ROOT = Path(__file__).resolve().parent


def _requests_full_suite(arguments: Sequence[str]) -> bool:
    for argument in arguments:
        if argument.startswith("-"):
            continue
        path_text = argument.split("::", maxsplit=1)[0]
        if Path(path_text).resolve() == TEST_ROOT:
            return True
    return False


def require_safe_full_suite(
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> None:
    if not _requests_full_suite(arguments):
        return
    current_environment = os.environ if environment is None else environment
    if current_environment.get(FULL_SUITE_LEASE_ENV) == FULL_SUITE_LEASE_VALUE:
        return
    raise pytest.UsageError(
        "The complete xinao_discovery test directory requires the serialized runner: "
        "uv run --frozen --extra dev --extra workflow python "
        "scripts/run_xinao_discovery_regression.py. "
        "Targeted files and subdirectories remain available without the heavy-suite lease."
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    invocation_arguments = list(session.config.invocation_params.args)
    collected_arguments = list(session.config.args)
    require_safe_full_suite([*invocation_arguments, *collected_arguments])
