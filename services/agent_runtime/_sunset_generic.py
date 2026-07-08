"""Generate wave5 sunset stubs for retired handroll modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

STUB_HEADER = '''"""SUNSET stub wave5 — default path: integrated_bus_v2. Retired: {module_name}."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from services.agent_runtime._sunset_module_stub import build_retired_module_payload

SCHEMA_VERSION = "xinao.codex_s.{state_name}.v1"
SENTINEL = "SENTINEL:XINAO_{state_upper}_SUNSET_STUB_V1"
STATE_NAME = "{state_name}"
TASK_ID = "{state_name}_sunset"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\\XINAO_RESEARCH_RUNTIME"))


def _payload(**kwargs: Any) -> dict[str, Any]:
    write = bool(kwargs.pop("write", True))
    runtime_root = Path(kwargs.pop("runtime_root", DEFAULT_RUNTIME))
    passed = bool(kwargs.pop("validation_passed", False))
    payload = build_retired_module_payload(
        module_name=STATE_NAME,
        status=f"{{STATE_NAME}}_sunset",
        state_dir=STATE_NAME,
        runtime_root=runtime_root,
        write=write,
        validation_passed=passed,
    )
    payload["schema_version"] = SCHEMA_VERSION
    payload["sentinel"] = SENTINEL
    payload["handroll_intact"] = False
    payload["delegated_from"] = "{module_name}"
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
'''


def state_name_from_filename(filename: str) -> str:
    return Path(filename).stem


def write_sunset_stub(target: Path) -> None:
    state_name = state_name_from_filename(target.name)
    state_upper = state_name.upper().replace("-", "_")
    content = STUB_HEADER.format(
        module_name=target.name,
        state_name=state_name,
        state_upper=state_upper,
    )
    target.write_text(content, encoding="utf-8", newline="\n")


def apply_wave5_stubs(
    runtime_dir: Path,
    *,
    min_kb: float = 25.0,
    keep_prefixes: tuple[str, ...] = (
        "integrated_bus",
        "thin_glue",
        "thin_bootstrap",
        "thin_evidence",
        "_sunset",
        "phase0_minimal",
        "closure_test",
        "codex_default_task",
        "codex_centric",
        "memory_budget",
        "completion_claim",
        "rollback_executor",
        "task_package_resolver",
        "temporal_codex_task_workflow",
        "root_intent_loop",
        "modular_dynamic_worker",
        "v4pro_mature_bind",
        "current_task_source",
        "worker_dispatch",
        "pre_pass_audit",
        "codex_native_provider",
        "codex_s_light_research",
        "tool_table_coverage",
        "thin_glue_sunset",
        "sunset_deprecation",
        "bounded_result_wait",
        "cheap_worker_patch",
    ),
) -> list[str]:
    replaced: list[str] = []
    for path in sorted(runtime_dir.glob("*.py")):
        if any(path.name.startswith(prefix) for prefix in keep_prefixes):
            continue
        if path.stat().st_size < int(min_kb * 1024):
            continue
        write_sunset_stub(path)
        replaced.append(path.name)
    return replaced