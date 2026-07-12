"""Resolve packaged module configuration with a source-tree development fallback."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any


def resolve_module_config(name: str) -> Path:
    packaged = Path(__file__).resolve().parent / "configs" / f"{name}.toml"
    if packaged.is_file():
        return packaged
    source = Path(__file__).resolve().parents[2] / "configs" / "modules" / f"{name}.toml"
    return source


def load_module_config(name: str) -> tuple[dict[str, Any], dict[str, object]]:
    path = resolve_module_config(name)
    raw: dict[str, Any] = {}
    if path.is_file():
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
        if isinstance(loaded, dict):
            raw = loaded
    data = path.read_bytes() if path.is_file() else b""
    return raw, {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": hashlib.sha256(data).hexdigest() if data else None,
    }
