"""SUNSET stub wave5 — default path: integrated_bus_v2. Retired: metaminute_preflight_reflection.py."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from services.agent_runtime._sunset_module_stub import build_retired_module_payload

SCHEMA_VERSION = "xinao.codex_s.metaminute_preflight_reflection.v1"
SENTINEL = "SENTINEL:XINAO_METAMINUTE_PREFLIGHT_REFLECTION_SUNSET_STUB_V1"
STATE_NAME = "metaminute_preflight_reflection"
TASK_ID = "metaminute_preflight_reflection_sunset"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))


def _payload(**kwargs: Any) -> dict[str, Any]:
    write = bool(kwargs.pop("write", True))
    runtime_root = Path(kwargs.pop("runtime_root", DEFAULT_RUNTIME))
    passed = bool(kwargs.pop("validation_passed", False))
    payload = build_retired_module_payload(
        module_name=STATE_NAME,
        status=f"{STATE_NAME}_sunset",
        state_dir=STATE_NAME,
        runtime_root=runtime_root,
        write=write,
        validation_passed=passed,
    )
    payload["schema_version"] = SCHEMA_VERSION
    payload["sentinel"] = SENTINEL
    payload["handroll_intact"] = False
    payload["delegated_from"] = "metaminute_preflight_reflection.py"
    return payload


def build(**kwargs: Any) -> dict[str, Any]:
    return _payload(**kwargs)


def run(**kwargs: Any) -> dict[str, Any]:
    return _payload(**kwargs)


def run_wave(**kwargs: Any) -> dict[str, Any]:
    return _payload(**kwargs)


def build_controller(**kwargs: Any) -> dict[str, Any]:
    return _payload(**kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SUNSET stub — use integrated_bus_v2")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = _payload(runtime_root=args.runtime_root, write=not args.no_write)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0


def __getattr__(name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(name)

    def _delegate(**kwargs: Any) -> dict[str, Any]:
        return _payload(**kwargs)

    _delegate.__name__ = name
    return _delegate
