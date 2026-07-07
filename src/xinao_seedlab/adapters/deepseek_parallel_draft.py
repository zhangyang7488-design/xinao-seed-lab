from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from xinao_seedlab.adapters.local_fs import utf8_safe


def _decode_stream(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class DeepSeekParallelDraftAdapter:
    """Thin adapter over the existing agent_runtime draft-deepseek launcher."""

    def __init__(self, runtime_root: str | Path = "D:/XINAO_RESEARCH_RUNTIME") -> None:
        self.runtime_root = Path(runtime_root)
        self.repo_root = Path(__file__).resolve().parents[3]
        self.launcher_ref = self.repo_root / "services" / "agent_runtime" / "agent_runtime.py"

    def invoke(
        self,
        *,
        task_id: str,
        objective: str,
        source_text: str,
        draft_quality_target: str = "70-80%",
        timeout_seconds: int = 240,
    ) -> dict[str, Any]:
        request = utf8_safe(
            {
                "task_id": task_id,
                "objective": objective,
                "source_text": source_text,
                "draft_quality_target": draft_quality_target,
                "final_owner": "codex",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(self.launcher_ref),
                "--runtime",
                str(self.runtime_root),
                "draft-deepseek",
            ],
            input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
            cwd=str(self.repo_root),
        )
        stdout = str(utf8_safe(_decode_stream(completed.stdout).strip()))
        stderr = str(utf8_safe(_decode_stream(completed.stderr).strip()))
        try:
            payload = utf8_safe(json.loads(stdout)) if stdout else {}
        except json.JSONDecodeError:
            payload = {}
        ok = (
            completed.returncode == 0
            and payload.get("ok") is True
            and payload.get("status") == "DRAFT_READY"
        )
        return utf8_safe(
            {
                "ok": ok,
                "returncode": completed.returncode,
                "launcher_ref": str(self.launcher_ref),
                "launcher_subcommand": "draft-deepseek",
                "request": request,
                "response": payload,
                "stdout_excerpt": stdout[:1000],
                "stderr_excerpt": stderr[:1000],
                "named_blocker": ""
                if ok
                else str(
                    payload.get("named_blocker") or "DEEPSEEK_PARALLEL_DRAFT_INVOCATION_FAILED"
                ),
            }
        )
