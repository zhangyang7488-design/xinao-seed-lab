"""L7 数据版本薄绑 — DVC import + version probe (thin_bind, no remote)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import (
    DEFAULT_RUNTIME,
    SCHEMA_VERSION,
    SENTINEL,
    now_iso,
    write_json,
)

TASK_ID = "thin_glue_dvc"
REPLACES_MODULE = "dataset_version_handroll"


def probe_dvc_import() -> dict[str, Any]:
    try:
        import dvc  # noqa: F401
    except ImportError as exc:
        return {
            "adapter": "dvc_import",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "DVC_NOT_INSTALLED",
        }
    import dvc as dvc_mod

    return {
        "adapter": "dvc_import",
        "ok": True,
        "skipped": False,
        "version": getattr(dvc_mod, "__version__", "unknown"),
    }


def probe_dvc_cli() -> dict[str, Any]:
    exe = shutil.which("dvc")
    if not exe:
        return {
            "adapter": "dvc_cli",
            "ok": False,
            "skipped": True,
            "reason": "dvc_cli_missing",
            "named_blocker": "DVC_CLI_MISSING",
        }
    try:
        completed = subprocess.run(
            [exe, "version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return {
            "adapter": "dvc_cli",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "DVC_VERSION_FAILED",
        }
    if completed.returncode != 0:
        return {
            "adapter": "dvc_cli",
            "ok": False,
            "skipped": True,
            "reason": (completed.stderr or completed.stdout or "dvc_version_failed").strip()[:300],
            "named_blocker": "DVC_VERSION_FAILED",
        }
    return {
        "adapter": "dvc_cli",
        "ok": True,
        "skipped": False,
        "version_excerpt": (completed.stdout or completed.stderr or "")[:200],
    }


def probe_dvc_module_version() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "dvc", "version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return {
            "adapter": "dvc_module",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "DVC_MODULE_VERSION_FAILED",
        }
    if completed.returncode != 0:
        return {
            "adapter": "dvc_module",
            "ok": False,
            "skipped": True,
            "reason": (completed.stderr or completed.stdout or "dvc_module_version_failed").strip()[
                :300
            ],
            "named_blocker": "DVC_MODULE_VERSION_FAILED",
        }
    return {
        "adapter": "dvc_module",
        "ok": True,
        "skipped": False,
        "version_excerpt": (completed.stdout or completed.stderr or "")[:200],
    }


def run_dvc_minimal_invoke(*, workspace: Path) -> dict[str, Any]:
    """Minimal in-process DVC init — invoke_green without remote (git repo required)."""
    workspace.mkdir(parents=True, exist_ok=True)
    dvc_dir = workspace / ".dvc"
    if dvc_dir.is_dir() and (dvc_dir / "config").is_file():
        return {
            "adapter": "dvc_init",
            "ok": True,
            "skipped": False,
            "workspace": str(workspace),
            "dvc_dir": str(dvc_dir),
            "git_initialized": (workspace / ".git").is_dir(),
            "reused_existing": True,
        }
    data_file = workspace / "smoke.csv"
    data_file.write_text("x,y\n1,2\n", encoding="utf-8")
    git_exe = shutil.which("git")
    if not git_exe:
        return {
            "adapter": "dvc_init",
            "ok": False,
            "skipped": True,
            "reason": "git_cli_missing",
            "named_blocker": "GIT_CLI_MISSING",
            "workspace": str(workspace),
        }
    try:
        git_init = subprocess.run(
            [git_exe, "init", "-q"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return {
            "adapter": "dvc_init",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "GIT_INIT_FAILED",
            "workspace": str(workspace),
        }
    if git_init.returncode != 0:
        return {
            "adapter": "dvc_init",
            "ok": False,
            "skipped": True,
            "reason": (git_init.stderr or git_init.stdout or "git_init_failed").strip()[:300],
            "named_blocker": "GIT_INIT_FAILED",
            "workspace": str(workspace),
        }
    exe = shutil.which("dvc")
    cmd = (
        [exe, "init", "--no-scm", "-q"]
        if exe
        else [sys.executable, "-m", "dvc", "init", "--no-scm", "-q"]
    )
    try:
        completed = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return {
            "adapter": "dvc_init",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "DVC_INIT_FAILED",
            "workspace": str(workspace),
        }
    if completed.returncode != 0:
        return {
            "adapter": "dvc_init",
            "ok": False,
            "skipped": True,
            "reason": (completed.stderr or completed.stdout or "dvc_init_failed").strip()[:300],
            "named_blocker": "DVC_INIT_FAILED",
            "workspace": str(workspace),
        }
    return {
        "adapter": "dvc_init",
        "ok": True,
        "skipped": False,
        "workspace": str(workspace),
        "dvc_dir": str(workspace / ".dvc"),
        "git_initialized": True,
    }


def run_dvc_bind_probe(*, runtime: Path | None = None) -> dict[str, Any]:
    imported = probe_dvc_import()
    cli = probe_dvc_cli()
    module = probe_dvc_module_version()
    bind_ok = imported.get("ok") is True and (cli.get("ok") is True or module.get("ok") is True)
    named_blocker = None
    if not imported.get("ok"):
        named_blocker = imported.get("named_blocker")
    elif not (cli.get("ok") or module.get("ok")):
        named_blocker = cli.get("named_blocker") or module.get("named_blocker")
    invoke: dict[str, Any] = {}
    invoke_ok = False
    if bind_ok:
        rt = runtime or DEFAULT_RUNTIME
        invoke = run_dvc_minimal_invoke(workspace=rt / "state" / "thin_glue_dvc" / "workspace")
        invoke_ok = invoke.get("ok") is True
        if not invoke_ok:
            named_blocker = invoke.get("named_blocker") or "DVC_INIT_FAILED"
    ok = bind_ok and invoke_ok
    return {
        "adapter": "dvc_invoke_green",
        "ok": ok,
        "skipped": not ok,
        "thin_bind": bind_ok and not invoke_ok,
        "invoke_green": invoke_ok,
        "invoke_ok": invoke_ok,
        "import_probe": imported,
        "cli_probe": cli,
        "module_probe": module,
        "invoke": invoke,
        "named_blocker": named_blocker,
        "remote_required": False,
    }


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_dvc"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_dvc_latest.md",
    }


def run_dvc_smoke(
    *,
    runtime: Path | None = None,
    run_id: str | None = None,
    write_evidence: bool = True,
) -> dict[str, Any]:
    rt = runtime or DEFAULT_RUNTIME
    resolved_run_id = run_id or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    bind = run_dvc_bind_probe(runtime=rt)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "layer": "L7",
        "replaces": REPLACES_MODULE,
        "run_id": resolved_run_id,
        "timestamp": now_iso(),
        "invoke_ok": bind.get("ok") is True,
        "dvc_ok": bind.get("ok") is True,
        "L7_dvc_ok": bind.get("ok") is True,
        "L7_dvc_invoke_green": bind.get("invoke_green") is True,
        "L7_dvc_thin_bind": bind.get("thin_bind") is True,
        "named_blocker": bind.get("named_blocker"),
        "bind": bind,
    }
    if write_evidence:
        paths = output_paths(rt)
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# thin_glue_dvc",
                    f"- invoke_ok: {payload['invoke_ok']}",
                    f"- thin_bind: {bind.get('thin_bind')}",
                    f"- named_blocker: {bind.get('named_blocker') or 'none'}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["output_paths"] = {k: str(v) for k, v in paths.items()}
    return payload


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="DVC thin-bind probe")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    args = parser.parse_args()
    payload = run_dvc_smoke(runtime=Path(args.runtime_root))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("invoke_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
