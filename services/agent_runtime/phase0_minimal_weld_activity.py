"""Phase0 minimal weld — markitdown intake → e2b/docker sandbox → git commit → D盘证据."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_bootstrap_runner import git_commit_all
from services.agent_runtime.thin_bootstrap_sandbox import run_cheapest_sandbox
from services.agent_runtime.thin_glue_stack import l0_intake_markdown

SCHEMA_VERSION = "xinao.codex_s.phase0_minimal_weld.v1"
SENTINEL = "SENTINEL:XINAO_PHASE0_MINIMAL_WELD_READY"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_INPUT = Path(r"C:\Users\xx363\Desktop\新系统\test_phase0_input.md")
FALLBACK_INPUT = DEFAULT_REPO / "materials" / "phase0_test_input.md"
PROOF_NAME = "phase0_proof.txt"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def resolve_phase0_input(input_path: Path | None = None) -> Path:
    if input_path and input_path.is_file():
        return input_path
    if DEFAULT_INPUT.is_file():
        return DEFAULT_INPUT
    if FALLBACK_INPUT.is_file():
        return FALLBACK_INPUT
    raise FileNotFoundError(
        f"phase0 input missing: provide --input or create {DEFAULT_INPUT} or {FALLBACK_INPUT}"
    )


def run_phase0_minimal_weld(
    input_path: Path | None = None,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    prefer_e2b: bool = True,
    prefer_docker: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    trigger = resolve_phase0_input(input_path)
    intake = l0_intake_markdown(trigger, max_chars=2000)
    task_md = str(intake.get("content_md") or "")
    preview = task_md[:300].replace('"', "'").replace("\n", " ")
    sandbox_code = (
        "from datetime import datetime\n"
        f'print("Phase0", datetime.now().isoformat())\n'
        f'print("{preview}...")\n'
    )
    sandbox = run_cheapest_sandbox(
        sandbox_code,
        prefer_e2b=prefer_e2b and bool(os.environ.get("E2B_API_KEY")),
        prefer_docker=prefer_docker,
    )
    exec_ok = sandbox.exit_code == 0 and bool(sandbox.stdout.strip())
    exec_output = sandbox.stdout or sandbox.stderr

    proof_path = repo_root / PROOF_NAME
    proof_path.write_text(f"{_now_iso()}\n{exec_output}\n", encoding="utf-8")
    commit_info = git_commit_all(repo_root, "Phase0: minimal weld")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    checks = {
        "L0_intake_converted": bool(task_md.strip()),
        "sandbox_executed": exec_ok,
        "sandbox_backend_external": sandbox.backend.startswith(("e2b", "docker:")),
        "phase0_proof_written": proof_path.is_file(),
        "git_commit_hash": bool(commit_info.get("commit_hash")),
        "evidence_json_ready": not write,
    }

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "phase": "0",
        "not_333_mainline": True,
        "thin_glue_phase0": True,
        "run_id": run_id,
        "intake": {
            "source": str(trigger),
            "content_md": task_md,
            "adapter": intake.get("adapter"),
            "timestamp": intake.get("timestamp"),
        },
        "execution": {
            "backend": sandbox.backend,
            "exit_code": sandbox.exit_code,
            "output": exec_output,
            "prefer_e2b": prefer_e2b,
            "e2b_api_key_present": bool(os.environ.get("E2B_API_KEY")),
        },
        "commit_hash": commit_info.get("commit_hash"),
        "commit_message": commit_info.get("commit_message"),
        "commit_created_new": commit_info.get("created_new"),
        "proof_path": str(proof_path),
        "acceptance_now_can_invoke_cn": (
            f"Phase0 最小环：{intake.get('adapter')} intake → {sandbox.backend} 执行 → "
            f"commit {str(commit_info.get('commit_hash', ''))[:12]}；证据落 D 盘 readback。"
            if exec_ok and commit_info.get("commit_hash")
            else "Phase0 未绿：检查 sandbox 或 git"
        ),
        "validation": {
            "passed": False,
            "checks": checks,
            "validated_at": _now_iso(),
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_source_of_truth": True,
    }

    if write:
        evidence_path = runtime_root / "readback" / f"phase0_{run_id}.json"
        checks["evidence_json_ready"] = True
        payload["evidence_path"] = str(evidence_path)
        passed = all(
            [
                checks["L0_intake_converted"],
                checks["sandbox_executed"],
                checks["phase0_proof_written"],
                checks["git_commit_hash"],
                checks["evidence_json_ready"],
            ]
        )
        payload["validation"]["passed"] = passed
        _write_json(evidence_path, payload)
        zh_path = runtime_root / "readback" / "zh" / f"phase0_{run_id}.md"
        zh_path.parent.mkdir(parents=True, exist_ok=True)
        zh_path.write_text(
            "\n".join(
                [
                    f"# Phase0 minimal weld {run_id}",
                    f"- backend: `{sandbox.backend}`",
                    f"- commit: `{commit_info.get('commit_hash', '')[:12]}`",
                    f"- passed: {passed}",
                    "",
                    payload["acceptance_now_can_invoke_cn"],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["readback_zh"] = str(zh_path)
    else:
        payload["validation"]["passed"] = exec_ok and bool(commit_info.get("commit_hash"))

    return payload


try:
    from temporalio import activity as _temporal_activity
except Exception:  # pragma: no cover

    class _MissingActivity:
        @staticmethod
        def defn(fn=None, *, name: str | None = None):
            def wrap(f):
                return f

            return wrap if fn is None else wrap(fn)

    _temporal_activity = _MissingActivity()  # type: ignore[misc, assignment]


@_temporal_activity.defn(name="phase0_minimal_intake_and_execute")
async def phase0_minimal_intake_and_execute(test_input_path: str) -> dict[str, Any]:
    return run_phase0_minimal_weld(
        Path(test_input_path),
        prefer_e2b=True,
        prefer_docker=True,
        write=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase0 minimal weld (e2b/docker, not mainline)")
    parser.add_argument("--input", default="")
    parser.add_argument("--no-e2b", action="store_true")
    parser.add_argument("--no-docker", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    try:
        payload = run_phase0_minimal_weld(
            input_path,
            prefer_e2b=not args.no_e2b,
            prefer_docker=not args.no_docker,
            write=not args.no_write,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())