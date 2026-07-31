#!/usr/bin/env python3
"""Deterministic collection-time pytest sharding for CI (no pytest-xdist).

Assignment is a pure function of the collected node ID and the shard
count/index, using SHA-256 (stable across processes and independent of
PYTHONHASHSEED). Local ``uv run pytest -q`` is unchanged unless this
plugin is loaded *and* ``--shard-count`` is set.

CI usage (exact matrix count/index + unique basetemp)::

    uv run pytest -q -p scripts.pytest_shard \\
      --shard-count 3 --shard-index 0 \\
      --basetemp "${{ runner.temp }}/pytest-shard-0"
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Final

import pytest

# Explicitly versioned stable digest; never use Python's randomized hash().
HASH_ALGORITHM: Final[str] = "sha256"

__all__ = (
    "HASH_ALGORITHM",
    "assign_shard",
    "partition_nodeids",
    "pytest_addoption",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "select_for_shard",
    "validate_shard_config",
)


def validate_shard_config(*, count: int, index: int) -> None:
    """Fail closed on invalid shard configuration."""
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError(f"shard count must be a positive int, got {count!r}")
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError(f"shard index must be a non-negative int, got {index!r}")
    if count < 1:
        raise ValueError(f"shard count must be >= 1, got {count}")
    if index < 0 or index >= count:
        raise ValueError(
            f"shard index must satisfy 0 <= index < count; got index={index}, count={count}"
        )


def assign_shard(nodeid: str, *, count: int) -> int:
    """Return deterministic shard index for a pytest node ID.

    Uses SHA-256 over the UTF-8 nodeid bytes, then modular reduction.
    """
    validate_shard_config(count=count, index=0)
    if not isinstance(nodeid, str):
        raise TypeError(f"nodeid must be str, got {type(nodeid).__name__}")
    digest = hashlib.new(HASH_ALGORITHM, nodeid.encode("utf-8")).digest()
    # Big-endian full digest as int → uniform enough modular assignment.
    return int.from_bytes(digest, byteorder="big") % count


def select_for_shard(nodeids: Sequence[str], *, count: int, index: int) -> list[str]:
    """Select node IDs belonging to one shard; reject duplicate IDs."""
    validate_shard_config(count=count, index=index)
    seen: set[str] = set()
    selected: list[str] = []
    for nodeid in nodeids:
        if nodeid in seen:
            raise ValueError(f"duplicate node id in collection: {nodeid!r}")
        seen.add(nodeid)
        if assign_shard(nodeid, count=count) == index:
            selected.append(nodeid)
    return selected


def partition_nodeids(nodeids: Sequence[str], *, count: int) -> list[list[str]]:
    """Partition node IDs into ``count`` shards; union/disjoint invariants hold."""
    validate_shard_config(count=count, index=0)
    buckets: list[list[str]] = [[] for _ in range(count)]
    seen: set[str] = set()
    for nodeid in nodeids:
        if nodeid in seen:
            raise ValueError(f"duplicate node id in collection: {nodeid!r}")
        seen.add(nodeid)
        buckets[assign_shard(nodeid, count=count)].append(nodeid)
    return buckets


def pytest_addoption(parser) -> None:  # type: ignore[no-untyped-def]
    group = parser.getgroup("pytest-shard")
    group.addoption(
        "--shard-count",
        action="store",
        type=int,
        default=None,
        help="Total number of deterministic shards (omit for no sharding).",
    )
    group.addoption(
        "--shard-index",
        action="store",
        type=int,
        default=None,
        help="Zero-based shard index for this process (requires --shard-count).",
    )


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    count = config.getoption("--shard-count")
    index = config.getoption("--shard-index")
    if count is None and index is None:
        return
    if count is None or index is None:
        raise pytest.UsageError(
            "both --shard-count and --shard-index are required when sharding is enabled"
        )
    try:
        validate_shard_config(count=count, index=index)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    config._xinao_pytest_shard = (count, index)  # type: ignore[attr-defined]


def pytest_collection_modifyitems(config, items) -> None:  # type: ignore[no-untyped-def]
    shard = getattr(config, "_xinao_pytest_shard", None)
    if shard is None:
        return
    count, index = shard

    # Fail closed on duplicate node IDs before any deselection.
    nodeids = [item.nodeid for item in items]
    seen: set[str] = set()
    for nodeid in nodeids:
        if nodeid in seen:
            raise pytest.UsageError(f"duplicate node id in collection: {nodeid!r}")
        seen.add(nodeid)

    selected: list = []
    deselected: list = []
    for item in items:
        if assign_shard(item.nodeid, count=count) == index:
            selected.append(item)
        else:
            deselected.append(item)

    if not selected:
        raise pytest.UsageError(
            f"shard index {index}/{count} selected zero tests "
            f"from {len(items)} collected item(s); refusing empty shard"
        )

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected
