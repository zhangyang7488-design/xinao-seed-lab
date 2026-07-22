"""Per-family deterministic world builders for H01-H14."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..constants import FAMILY_IDS
from ..stream import DeterministicStream
from . import group_a, group_b

FamilyBuilder = Callable[[DeterministicStream, str, int], dict[str, Any]]

_BUILDERS: dict[str, FamilyBuilder] = {
    "H01": group_a.build_h01,
    "H02": group_a.build_h02,
    "H03": group_a.build_h03,
    "H04": group_a.build_h04,
    "H05": group_a.build_h05,
    "H06": group_a.build_h06,
    "H07": group_a.build_h07,
    "H08": group_b.build_h08,
    "H09": group_b.build_h09,
    "H10": group_b.build_h10,
    "H11": group_b.build_h11,
    "H12": group_b.build_h12,
    "H13": group_b.build_h13,
    "H14": group_b.build_h14,
}

assert tuple(_BUILDERS.keys()) == FAMILY_IDS


def build_family_world(
    family_id: str,
    stream: DeterministicStream,
    *,
    split: str,
    case_index: int,
) -> dict[str, Any]:
    """Return raw public/private pieces for one family case (pre-commitment)."""
    if family_id not in _BUILDERS:
        raise KeyError(f"unknown family_id: {family_id}")
    return _BUILDERS[family_id](stream, split, case_index)


def registered_family_ids() -> tuple[str, ...]:
    return FAMILY_IDS


__all__ = ["build_family_world", "registered_family_ids"]
