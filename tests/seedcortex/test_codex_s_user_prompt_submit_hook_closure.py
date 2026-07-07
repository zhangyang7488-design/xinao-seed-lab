import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hardmode" / "Invoke-CodexSUserPromptSubmitHook.ps1"


def _last_json_line(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if text.startswith("{"):
            return json.loads(text)
    return {}


def test_user_prompt_submit_routes_closure_prompt_to_mutation_owner(tmp_path: Path) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the S UserPromptSubmit hook wrapper")

    runtime = tmp_path / "runtime"
    event = {
        "hook_event_name": "UserPromptSubmit",
        "user_prompt": "全部收口：默认主路绑定、运行态加载、证据/readback、提交推送合并",
    }
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepoRoot",
            str(REPO_ROOT),
            "-RuntimeRoot",
            str(runtime),
        ],
        input=json.dumps(event, ensure_ascii=False),
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = _last_json_line(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "closure evidence bundle" in context
    assert "codex_mutation_final_owner" in context
    latest = runtime / "state" / "codex_s_user_prompt_submit_hook" / "latest.json"
    state = json.loads(latest.read_text(encoding="utf-8-sig"))
    assert state["token_budget_gate"]["route_id"] == "codex_mutation_final_owner"
    assert "execution_closure" in state["execution_subclasses"]
