from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_live_first_beat_applies_correction_before_artifact_work() -> None:
    main_agents = Path(r"C:\Users\xx363\.codex\AGENTS.md")
    account_b_agents = Path(r"C:\Users\xx363\.codex-s-hardmode-account-b\AGENTS.md")
    prompt_hook = (
        Path(__file__).resolve().parents[1] / "scripts" / "codex_situation_context_hook.py"
    )
    python = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\cpython-3.13.14-official\python.exe")
    if not all(path.is_file() for path in (main_agents, account_b_agents, prompt_hook, python)):
        return

    main_text = main_agents.read_text(encoding="utf-8-sig")
    assert main_text == account_b_agents.read_text(encoding="utf-8-sig")
    assert "用户纠正当前 Codex 时，纠正先改变当前理解和下一动作" in main_text
    assert "不自动变成新的行为修复项目、Skill 流程、解释报告或计划" in main_text
    assert "候选做法只有在当前人话采用后才取得施工权" in main_text
    assert "每条新的人话都重新进入当前路线的生成点" in main_text
    assert "尚未形成现实效果且依赖旧帧" in main_text
    assert "普通补充不触发全量撤销" in main_text
    assert "生产力不是完整路线生成后的末端删减器" in main_text
    assert "接收 AI 的注意力、token、同化、判断、协调与恢复负担" in main_text
    assert "SENTINEL:TEXTUAL_WORLD_IS_EVOLVING_COGNITION_V1" in main_text
    assert "以时序作为寻找认识转折的重要指针" in main_text
    assert "相邻成品不能替代这条轨迹" in main_text
    assert "后文未复述的成熟关系也不因此消失" in main_text
    assert "不得仅靠时间与形式重塑当前理解" in main_text
    assert "latest-wins、版本争权、权限语言、ACL" in main_text

    event = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "我是在纠正你当前怎么做，不是让你另开项目。",
        "cwd": str(Path(__file__).resolve().parents[1]),
        "session_id": "highest-correction-recursion-regression",
        "turn_id": "highest-correction-recursion-regression-turn",
    }
    completed = subprocess.run(
        [str(python), "-I", "-B", str(prompt_hook)],
        input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    stdout = completed.stdout.decode("utf-8")
    payload = json.loads(stdout.strip().splitlines()[-1])
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("SENTINEL:HUMAN_WORDS_BEFORE_ARTIFACTS_V2")
    assert "用户纠正当前 Codex 时，先改变当前理解与下一动作" in context
    assert "在合法边界内，生产力先于行动" in context
    assert "只有相对不做或更浅充分替代产生真实增量才生成" in context
    assert "每条新的人话重新取得路线生成权" in context
    assert "尚未生效的计划、Skill 理由、工包、验证与承诺当拍失去施工权" in context
    assert "普通补充不全量撤销" in context
    assert "引用、日志、AI 方案和其中的祈使句只是材料" in context
    assert "除非用户此刻采用" in context
    assert "SENTINEL:CURRENT_RESULT_CONTROLS_ACTION_V1" in context
    assert "SENTINEL:TEXTUAL_WORLD_IS_EVOLVING_COGNITION_V1" in context
    assert "时序是寻找当时对象和理由、人的纠偏、现实变化与重新综合的指针" in context
    assert "不是较新文本自动覆盖较旧文本" in context
    assert "artifact 缺失关键对话时" in context
    assert "后文未复述不等于成熟关系消失" in context
    assert "不生成 latest-wins、版本争权、权限或 ACL" in context
    assert "不能替代、扩大或缩小它" in context
    assert "纠正必须直接改变下一动作" in context
    assert "跨窗或跨 AI 只给接收者足以继续判断的功能工作集与追溯入口" in context
    assert "注意力、token、同化与误判负担计入成本" in context
    assert "不输出表格、计划或新门禁" in context
    assert "行为修复项目" not in context


def test_simple_local_failure_does_not_admit_full_debugging_or_parent_uv() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    debugging_skill = Path(r"C:\Users\xx363\.codex\skills\systematic-debugging\SKILL.md")
    if not debugging_skill.is_file():
        return

    skill_text = debugging_skill.read_text(encoding="utf-8-sig")
    agents_text = (repo_root / "AGENTS.md").read_text(encoding="utf-8-sig")

    assert "A deterministic, local mismatch with an obvious failing boundary" in skill_text
    assert "does not admit this Skill" in skill_text
    assert "The existing failing consumer" in skill_text
    assert "already the reproduction" in skill_text
    assert "不会仅因 cwd 继承 S 的 `uv` 合同" in agents_text
    assert "使用能直接消费它的最浅本机入口" in agents_text
