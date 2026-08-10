from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_live_first_beat_projects_highest_correction_recursion_burden() -> None:
    main_agents = Path(r"C:\Users\xx363\.codex\AGENTS.md")
    account_b_agents = Path(r"C:\Users\xx363\.codex-s-hardmode-account-b\AGENTS.md")
    prompt_hook = Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island"
        r"\scripts\user_prompt_zero_beat_v1.ps1"
    )
    pwsh = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4\pwsh.exe")
    if not all(path.is_file() for path in (main_agents, account_b_agents, prompt_hook, pwsh)):
        return

    main_text = main_agents.read_text(encoding="utf-8-sig")
    assert main_text == account_b_agents.read_text(encoding="utf-8-sig")
    assert "用户明确标记的最高级失败" in main_text
    assert "把每次纠正压成一个新的局部任务" in main_text
    assert "只有用户此刻明确把记录或行为修复本身设为活动对象时" in main_text

    event = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "我是在纠正你当前怎么做，不是让你另开项目。",
        "cwd": str(Path(__file__).resolve().parents[1]),
        "session_id": "highest-correction-recursion-regression",
        "turn_id": "highest-correction-recursion-regression-turn",
    }
    completed = subprocess.run(
        [str(pwsh), "-NoProfile", "-File", str(prompt_hook)],
        input=json.dumps(event, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("SENTINEL:")
    assert "用户明确标记的最高级失败" in context
    assert "把每次纠正压成新的局部任务" in context
    assert "只有用户此刻明确把记录或行为修复本身设为活动对象时" in context
    assert "纠正默认更新仍存活父帧、对象关系和下一动作" in context
    assert "不取得独立任务、Skill、流程或完成身份" in context
