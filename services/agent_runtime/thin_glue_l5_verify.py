"""L5 验收 — pytest-json-report 并进 thin-glue 默认链（替 verify PS1 马拉松）."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_evidence_writer import append_jsonl, now_iso, write_json
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

REPLACES_TARGET = "verify_*.ps1 marathon"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l5_verify.v1"
SENTINEL = "SENTINEL:XINAO_THIN_GLUE_L5_VERIFY_READY"
DEFAULT_TEST_PATHS = [
    "tests/test_closure_test_proof.py",
    "tests/test_thin_glue_work_proof.py",
    "tests/test_thin_bootstrap_runner.py",
    "tests/test_thin_glue_stack.py",
]


def thin_glue_verify_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_VERIFY", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def run_l5_pytest_verify(
    *,
    repo: Path,
    runtime: Path,
    run_id: str,
    test_paths: list[str] | None = None,
) -> dict[str, Any]:
    candidates = test_paths or list(DEFAULT_TEST_PATHS)
    selected = [p for p in candidates if (repo / p).is_file()]
    if not selected:
        return {
            "layer": "L5",
            "skipped": True,
            "passed": True,
            "reason": "no_pytest_targets_in_repo",
        }

    report_path = runtime / "evidence" / run_id / "pytest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *selected,
        "-q",
        "--json-report",
        f"--json-report-file={report_path}",
    ]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False)
    payload: dict[str, Any] = {
        "layer": "L5",
        "adapter": "pytest-json-report",
        "test_paths": selected,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-1000:],
        "report_path": str(report_path),
    }
    if report_path.is_file():
        try:
            payload["report"] = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["report"] = {}
    else:
        write_json(report_path, {"exit_code": proc.returncode, "tests": []})
    payload["passed"] = proc.returncode == 0
    payload["pytest_node_count"] = len(payload.get("report", {}).get("tests", []) or [])
    append_jsonl(
        runtime / "evidence" / run_id / "execution.jsonl",
        {"layer": "L5", "activity": "pytest", "passed": payload["passed"], "timestamp": now_iso()},
    )
    return payload


def _try_diff_cover(repo: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "diff_cover.diff_cover_tool", "--version"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"adapter": "diff-cover", "skipped": True, "reason": "diff_cover_not_installed"}
    if proc.returncode != 0:
        return {"adapter": "diff-cover", "skipped": True, "reason": "diff_cover_not_installed"}
    diff_proc = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if not (diff_proc.stdout or "").strip():
        return {"adapter": "diff-cover", "skipped": True, "reason": "no_git_diff"}
    cover_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_tool",
            "coverage.xml",
            "--fail-under=0",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return {
        "adapter": "diff-cover",
        "skipped": False,
        "exit_code": cover_proc.returncode,
        "stdout": (cover_proc.stdout or "")[-1500:],
        "hand_rolled_verify_ps1_bypassed": True,
    }


def run_thin_glue_l5_verify_layer(
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    test_paths: list[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    pytest_result = run_l5_pytest_verify(
        repo=repo,
        runtime=runtime,
        run_id=run_id,
        test_paths=test_paths,
    )
    diff_cover = _try_diff_cover(repo)
    passed = pytest_result.get("passed") is True
    acceptance_cn = (
        f"L5 薄验证：pytest-json-report {pytest_result.get('pytest_node_count', 0)} 节点绿；"
        "verify PS1 马拉松已旁路。"
        if passed
        else "L5 薄验证未绿：先修 pytest 目标或薄胶 loop。"
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "run_id": run_id,
        "thin_glue": True,
        "replaces": REPLACES_TARGET,
        "not_333_mainline": True,
        "handroll_intact": True,
        "hand_rolled_verify_ps1_bypassed": True,
        "pytest": pytest_result,
        "diff_cover": diff_cover,
        "acceptance_now_can_invoke_cn": acceptance_cn,
        "validation": {
            "passed": passed,
            "checks": {
                "pytest_json_report_green": passed,
                "hand_rolled_verify_ps1_bypassed": True,
            },
            "validated_at": run_id,
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
    }
    if write:
        latest = runtime / "state" / "thin_glue_l5_verify" / "latest.json"
        evidence = runtime / "readback" / f"thin_glue_l5_verify_{run_id}.json"
        write_json(latest, payload)
        write_json(evidence, payload)
        payload["output_paths"] = {"latest": str(latest), "evidence": str(evidence)}
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="L5 thin glue verify layer")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    payload = run_thin_glue_l5_verify_layer(
        runtime_root=Path(args.runtime_root),
        repo_root=Path(args.repo_root),
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())