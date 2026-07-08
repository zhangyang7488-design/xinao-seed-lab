"""Phase0 external-seam invoke — structure from temporalio/samples-python hello/hello_activity.py.

Seam sources (local mirror, not S wrapper platform):
  - Temporal: hello_activity.py (@workflow.defn + @activity.defn + Worker)
  - MarkItDown: official README API (MarkItDown().convert)
  - Docker: engine CLI python:3.12-slim (subprocess)
Params only: materials/authority_glue/seams/phase0_seam_params.v1.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PARAMS_PATH = Path(__file__).with_name("phase0_seam_params.v1.json")
SCHEMA_VERSION = "xinao.phase0_external_seam_invoke.v1"
SENTINEL = "SENTINEL:XINAO_PHASE0_EXTERNAL_SEAM_INVOKE_READY"


def _load_params(path: Path | None = None) -> dict[str, Any]:
    p = path or PARAMS_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _resolve_input(params: dict[str, Any]) -> Path:
    for key in ("input_path", "fallback_input_path"):
        candidate = Path(str(params.get(key, "")))
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("phase0 input missing; set input_path in phase0_seam_params.v1.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def markitdown_convert(path: Path, *, max_chars: int) -> dict[str, Any]:
    """microsoft/markitdown README: md = MarkItDown(); md.convert(...)"""
    seam = "microsoft/markitdown README API"
    try:
        from markitdown import MarkItDown

        text = (MarkItDown().convert(str(path)).text_content or "")[:max_chars]
        adapter = seam
    except Exception as exc:
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        adapter = f"plain_text_fallback ({exc.__class__.__name__})"
    return {
        "adapter": adapter,
        "source": str(path),
        "content_md": text,
        "char_count": len(text),
        "timestamp": _now_iso(),
    }


def docker_python_exec(code: str, *, image: str, timeout_s: int = 90) -> dict[str, Any]:
    proc = subprocess.run(
        ["docker", "run", "--rm", "-i", image, "python", "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return {
        "backend": f"docker:{image}",
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "exit_code": int(proc.returncode),
    }


def git_commit_all(repo_root: Path, message: str) -> dict[str, Any]:
    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

    if not (repo_root / ".git").exists():
        return {"commit_hash": None, "commit_message": message, "created_new": False, "error": "not a git repo"}
    _run("add", "-A")
    status = _run("status", "--porcelain")
    if not (status.stdout or "").strip():
        head = _run("rev-parse", "HEAD")
        return {
            "commit_hash": (head.stdout or "").strip() or None,
            "commit_message": message,
            "created_new": False,
        }
    commit = _run("commit", "-m", message)
    head = _run("rev-parse", "HEAD")
    return {
        "commit_hash": (head.stdout or "").strip() or None,
        "commit_message": message,
        "created_new": commit.returncode == 0,
        "stderr": (commit.stderr or "").strip(),
    }


@dataclass
class Phase0SeamInput:
    input_path: str
    params_path: str = str(PARAMS_PATH)


def run_phase0_seam_body(input_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    runtime_root = Path(params["runtime_root"])
    repo_root = Path(params["repo_root"])
    image = str(params.get("docker_image", "python:3.12-slim"))
    max_chars = int(params.get("max_md_chars", 2000))
    proof_name = str(params.get("proof_filename", "phase0_proof.txt"))

    intake = markitdown_convert(input_path, max_chars=max_chars)
    preview = str(intake.get("content_md") or "")[:300].replace('"', "'").replace("\n", " ")
    code = (
        "from datetime import datetime\n"
        f'print("Phase0-seam", datetime.now().isoformat())\n'
        f'print("{preview}...")\n'
    )
    execution = docker_python_exec(code, image=image)
    exec_ok = execution["exit_code"] == 0 and bool(execution["stdout"])
    exec_output = execution["stdout"] or execution["stderr"]

    proof_path = repo_root / proof_name
    proof_path.write_text(f"{_now_iso()}\n{exec_output}\n", encoding="utf-8")
    commit_info = git_commit_all(repo_root, "Phase0: external seam invoke")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    checks = {
        "L0_markitdown_intake": bool(str(intake.get("content_md") or "").strip()),
        "docker_executed": exec_ok,
        "proof_written": proof_path.is_file(),
        "git_commit_hash": bool(commit_info.get("commit_hash")),
    }
    passed = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "not_333_mainline": True,
        "external_seam_invoke": True,
        "external_seam_refs": params.get("external_seam_refs"),
        "params_path": str(PARAMS_PATH),
        "run_id": run_id,
        "intake": intake,
        "execution": execution,
        "commit_hash": commit_info.get("commit_hash"),
        "commit_created_new": commit_info.get("created_new"),
        "proof_path": str(proof_path),
        "acceptance_now_can_invoke_cn": (
            f"Phase0 外部接缝：{intake.get('adapter')} → {execution['backend']} → "
            f"commit {str(commit_info.get('commit_hash', ''))[:12]}；证据在 D 盘 readback。"
            if passed
            else "Phase0 接缝未绿：检查 markitdown/docker/git"
        ),
        "validation": {"passed": passed, "checks": checks, "validated_at": _now_iso()},
    }
    evidence_path = runtime_root / "readback" / f"phase0_seam_{run_id}.json"
    payload["evidence_path"] = str(evidence_path)
    _write_json(evidence_path, payload)
    zh_path = runtime_root / "readback" / "zh" / f"phase0_seam_{run_id}.md"
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.write_text(
        "\n".join(
            [
                f"# Phase0 external seam {run_id}",
                f"- markitdown: `{intake.get('adapter')}`",
                f"- sandbox: `{execution['backend']}`",
                f"- commit: `{str(commit_info.get('commit_hash', ''))[:12]}`",
                f"- passed: {passed}",
                "",
                payload["acceptance_now_can_invoke_cn"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload["readback_zh"] = str(zh_path)
    return payload


# --- Temporal hello_activity.py pattern (activity + workflow + worker main) ---

try:
    from temporalio import activity, workflow
    from temporalio.client import Client
    from temporalio.worker import Worker

    @activity.defn(name="xinao_phase0_external_seam_activity")
    def xinao_phase0_external_seam_activity(seam_input: Phase0SeamInput) -> dict[str, Any]:
        params = _load_params(Path(seam_input.params_path))
        return run_phase0_seam_body(Path(seam_input.input_path), params)

    @workflow.defn(name="XinaoPhase0ExternalSeamWorkflow")
    class XinaoPhase0ExternalSeamWorkflow:
        @workflow.run
        async def run(self, seam_input: Phase0SeamInput) -> dict[str, Any]:
            return await workflow.execute_activity(
                xinao_phase0_external_seam_activity,
                seam_input,
                start_to_close_timeout=timedelta(minutes=5),
            )

    TEMPORAL_AVAILABLE = True
except Exception:
    TEMPORAL_AVAILABLE = False


async def run_temporal_invoke(params: dict[str, Any], input_path: Path) -> dict[str, Any]:
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("temporalio not available")
    target = str(params.get("temporal_target", "127.0.0.1:7233"))
    task_queue = str(params["task_queue"])
    client = await Client.connect(target)
    seam_input = Phase0SeamInput(input_path=str(input_path), params_path=str(PARAMS_PATH))
    workflow_id = f"{params.get('workflow_id_prefix', 'xinao-phase0-seam')}-{uuid.uuid4().hex[:12]}"
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[XinaoPhase0ExternalSeamWorkflow],
        activities=[xinao_phase0_external_seam_activity],
        activity_executor=ThreadPoolExecutor(4),
    ):
        return await client.execute_workflow(
            XinaoPhase0ExternalSeamWorkflow.run,
            seam_input,
            id=workflow_id,
            task_queue=task_queue,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase0 external seam invoke (not_333_mainline)")
    parser.add_argument("--params", default=str(PARAMS_PATH))
    parser.add_argument("--input", default="")
    parser.add_argument("--local", action="store_true", help="skip Temporal; run activity body directly")
    parser.add_argument("--temporal", action="store_true", help="force Temporal hello_activity worker pattern")
    args = parser.parse_args(argv)

    params = _load_params(Path(args.params))
    input_path = Path(args.input) if args.input else _resolve_input(params)

    use_temporal = args.temporal or (not args.local and TEMPORAL_AVAILABLE)
    try:
        if use_temporal and TEMPORAL_AVAILABLE:
            payload = asyncio.run(run_temporal_invoke(params, input_path))
            mode = "temporal"
        else:
            payload = run_phase0_seam_body(input_path, params)
            mode = "local"
    except Exception as exc:
        print(json.dumps({"error": str(exc), "mode": "failed"}, ensure_ascii=False), file=sys.stderr)
        return 2

    payload["invoke_mode"] = mode
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())