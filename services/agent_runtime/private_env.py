from __future__ import annotations

import os
import pathlib
from typing import Any


DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")


def read_env_file(path: str | pathlib.Path) -> dict[str, str]:
    path = pathlib.Path(path)
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def private_env(runtime_root: str | pathlib.Path, name: str) -> dict[str, str]:
    return read_env_file(pathlib.Path(runtime_root) / "private" / name)


def get_private_env_value(
    key: str,
    *,
    runtime_root: str | pathlib.Path = DEFAULT_RUNTIME,
    env_file: str,
    default: str = "",
) -> str:
    if os.environ.get(key):
        return os.environ[key]
    return private_env(runtime_root, env_file).get(key, default)


def write_env_file_if_missing(path: str | pathlib.Path, values: dict[str, Any]) -> None:
    path = pathlib.Path(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
