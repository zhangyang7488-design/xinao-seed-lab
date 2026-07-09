"""B/C rules harvest worker — codex exec, write curated txt to Desktop folder."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(r"C:\Users\xx363\CodexWorkspaces\B\nianhua")
BRIDGE_ROOT = pathlib.Path(__file__).resolve().parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BRIDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BRIDGE_ROOT))

from grok_audit_common import ENGINEERING_PROFILES  # noqa: E402

DEFAULT_OUTPUT_ROOT = pathlib.Path(r"C:\Users\xx363\Desktop\GROK_GLOBAL_RULES_HARVEST_20260626")


def harvest_prompt(auditor: str, output_path: pathlib.Path, raw_dir: pathlib.Path) -> str:
    scope = {
        "B": (
            "Extract ALL rule-like text from: L0 bootstrap (D+B), default_backlog, "
            "codex_default_execution_frame, default_work_binding, constitution, behavior_kernel, "
            "B repo AGENTS.md and runtime/resources/startup, D control_panel policies, hooks. "
            f"Read raw copies under: {raw_dir}"
        ),
        "C": (
            "Extract rule-like text from C nianhua repo startup/rules, "
            "list A workspace rule files, summarize hooks.json lifecycle rules. "
            f"Read raw copies under: {raw_dir}"
        ),
    }[auditor]
    return (
        "You are a read-only rules harvest worker for global human audit preparation.\n"
        "Do NOT edit source repos. Do NOT claim completion.\n"
        f"Auditor: {auditor}\n"
        f"Scope: {scope}\n"
        "Output ONE plain-text file in Chinese where possible, structured as:\n"
        "  # 章节标题\n"
        "  ## 来源路径\n"
        "  摘录正文...\n"
        "  ---\n"
        "Include: path, short summary, key bullets, conflicts if any.\n"
        "Exclude: claiming user completion.\n"
        f"Write the complete harvest to this exact path using a single write tool or shell redirect:\n"
        f"{output_path}\n"
        "If too large, prioritize L0, backlog, execution_frame, constitution, AGENTS.\n"
        "Begin now."
    )


def run_harvest(profile: dict, prompt: str, timeout_seconds: int) -> dict:
    repo = profile["repo"]
    codex_home = profile["codex_home"]
    codex_binary = shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")
    if not codex_binary:
        raise FileNotFoundError("CODEX_CLI_NOT_FOUND")
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    work_dir = repo / "artifacts" / "grok_rules_harvest_scratch"
    work_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            codex_binary,
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "-C",
            str(repo),
            prompt,
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        env=env,
    )
    return {
        "returncode": completed.returncode,
        "stderr_tail": completed.stderr[-1500:],
        "stdout_tail": completed.stdout[-1500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auditor", choices=["B", "C"], required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    output_root = pathlib.Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    raw_dir = output_root / "raw"
    out_name = {
        "B": "01_B_工程规则_L0仓库运行时.txt",
        "C": "02_C_工程规则_备用仓.txt",
    }[args.auditor]
    output_path = output_root / out_name

    profile = ENGINEERING_PROFILES[args.auditor]
    prompt = harvest_prompt(args.auditor, output_path, raw_dir)
    result = run_harvest(profile, prompt, args.timeout_seconds)

    payload = {
        "auditor": args.auditor,
        "output_path": str(output_path),
        "output_exists": output_path.is_file(),
        "output_bytes": output_path.stat().st_size if output_path.is_file() else 0,
        **result,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if output_path.is_file() and output_path.stat().st_size > 200 else 2


if __name__ == "__main__":
    raise SystemExit(main())