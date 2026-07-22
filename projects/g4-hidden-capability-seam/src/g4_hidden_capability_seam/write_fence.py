"""Bounded write-fence inventory: no package writes outside allowed_write_root."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def normalize(path: str | Path) -> str:
    return str(Path(path).resolve()).lower()


def is_within(path: str | Path, root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def inventory_tree(root: str | Path) -> list[dict[str, Any]]:
    root_p = Path(root).resolve()
    items: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root_p):
        # skip pycache during inventory of retained? keep but finalize will clean
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(root_p).as_posix()
            items.append({"path": rel, "abs": str(p), "size": p.stat().st_size})
    return sorted(items, key=lambda x: x["path"])


def check_write_fence(
    *,
    allowed_write_root: str | Path,
    written_paths: list[str | Path],
) -> dict[str, Any]:
    root = Path(allowed_write_root).resolve()
    outside = []
    inside = []
    for p in written_paths:
        pp = Path(p).resolve()
        if is_within(pp, root):
            inside.append(str(pp))
        else:
            outside.append(str(pp))
    return {
        "ok": len(outside) == 0,
        "allowed_write_root": str(root),
        "inside_count": len(inside),
        "outside": outside,
        "reason": None if not outside else "write_outside_allowed_root",
    }
