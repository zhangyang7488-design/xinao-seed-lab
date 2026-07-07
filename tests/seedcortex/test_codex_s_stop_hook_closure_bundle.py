import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hardmode" / "Invoke-CodexSStopHook.ps1"


def _last_json_line(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if text.startswith("{"):
            return json.loads(text)
    return {}


def test_stop_hook_continues_when_closure_bundle_is_missing(tmp_path: Path) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the S Stop hook wrapper")

    event = {
        "hook_event_name": "Stop",
        "user_prompt": "全部收口：默认主路绑定、运行态加载、证据/readback、提交推送合并",
        "last_assistant_message": "收口完了。",
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
            str(tmp_path / "runtime"),
            "-SideAuditJsonOverride",
            json.dumps({"decision": "allow_stop", "suppressOutput": True}),
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
    assert payload["continue"] is True
    assert payload["reason"] == "closure_evidence_bundle_missing_or_incomplete"
    assert "default_mainline_weld_point" in payload["closureEvidenceBundle"]["missing_fields"]
    latest = tmp_path / "runtime" / "state" / "codex_s_stop_hook" / "latest.json"
    state = json.loads(latest.read_text(encoding="utf-8-sig"))
    assert state["delivery_first_default"]["default_acceptance_decisions"] == [
        "accepted_for_binding",
        "accepted_for_delivery",
    ]
    assert state["delivery_first_default"]["exception_acceptance_decision"] == (
        "accepted_for_next_frontier"
    )
    assert state["delivery_first_default"]["next_frontier_default_outlet"] is False
