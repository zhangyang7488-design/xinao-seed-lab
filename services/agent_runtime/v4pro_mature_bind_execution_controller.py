"""SUNSET stub — handroll deleted wave3; default → thin_glue_l3_execute."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.v4pro_mature_bind_execution_controller.v1"
SENTINEL = "SENTINEL:XINAO_V4PRO_MATURE_BIND_EXECUTION_CONTROLLER_SUNSET_STUB_V1"
TASK_ID = "p0_013_v4pro_mature_bind_execution_controller"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(
    os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统")
)


def build_controller(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_package_root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    write: bool = True,
    send_signal: bool = False,
    run_verification: bool = True,
    skip_verification: bool = False,
    write_aaq: bool = True,
) -> dict[str, Any]:
    del task_package_root, send_signal, run_verification, skip_verification, write_aaq
    from services.agent_runtime.thin_glue_l3_execute import run_thin_glue_l3_layer

    payload = run_thin_glue_l3_layer(
        runtime_root=Path(runtime_root),
        repo_root=Path(repo_root),
        write=write,
    )
    payload["delegated_from"] = "v4pro_mature_bind_execution_controller.build_controller"
    payload["task_id"] = TASK_ID
    payload["status"] = "v4pro_mature_bind_execution_controller_ready"
    payload["v4pro_mature_bind_execution_controller_ready"] = payload.get("validation", {}).get(
        "passed"
    ) is True
    payload["handroll_intact"] = False
    payload["sunset_stub"] = True
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build_controller(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())