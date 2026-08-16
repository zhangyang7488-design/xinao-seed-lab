from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_hot_s_contract_separates_guardian_and_world_continuity() -> None:
    agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "SENTINEL:S_GUARDIAN_AND_WORLD_CONTINUITY_SEPARATED_V1" in agreement
    assert "S 守护新仓库运行后，这个工程/effect 责任默认持续" in agreement
    assert "新仓库 world-owning Sol 的默认长期存续是另一层 cognition/world 语义" in agreement
    assert "S 不强迫它继续算" in agreement
    assert "固定 branch 数和 CLI 上限都不证明最大并发" in agreement
    assert "各自显式 runtime root" in agreement


def test_hot_s_builder_reenters_parent_frontier_without_conflating_world_wake() -> None:
    agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "SENTINEL:S_BUILDER_PARENT_FRONTIER_REENTRY_V1" in agreement
    assert "重建仍存活的父结果与未闭因果关系" in agreement
    assert "不能把 S 停在报告墙" in agreement
    assert "不是 Research Sol 的 `WAIT/wake` 生命周期" in agreement
    assert "不要求常驻 guardian" in agreement

    detailed = (
        REPO_ROOT / "docs" / "tool_glue" / "S_CONTROL_TOWER_PRIMARY_MODE_CURRENT.md"
    ).read_text(encoding="utf-8")
    assert "当前 S 建设者的父前沿回入" in detailed
    assert "RECONCILE PENDING TASK FRONTIER" in detailed
    assert "Research Sol 的 `WAIT/wake`" in detailed
    assert "三个不同生命周期层" in detailed


def test_detailed_control_tower_contract_preserves_dual_root_operations() -> None:
    contract = (
        REPO_ROOT / "docs" / "tool_glue" / "S_CONTROL_TOWER_PRIMARY_MODE_CURRENT.md"
    ).read_text(encoding="utf-8")
    assert "S guardian continuity" in contract
    assert "world cognition continuity" in contract
    assert "所有 Sol 暂时 `WAIT` 时，S 仍守护" in contract
    assert "任何 `branch_width=4`、默认值或 CLI 上限" in contract
    assert "一个 episode 内冻结一个 `account_slot`" in contract
    assert "A/C 同时存在后，所有运维命令必须显式给出各自 `--runtime-root`" in contract
    assert "A canary 使用独立 locator `...\\xinao_perpetual_a`" in contract


def test_hot_s_contract_routes_current_phenotype_focus_to_control_surface_only() -> None:
    agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    detailed = (
        REPO_ROOT / "docs" / "tool_glue" / "S_CONTROL_TOWER_PRIMARY_MODE_CURRENT.md"
    ).read_text(encoding="utf-8")
    focus_path = (
        REPO_ROOT
        / "docs"
        / "tool_glue"
        / "RESEARCH_SOL_COGNITION_PHENOTYPE_FOCUS_CURRENT.md"
    )
    focus = focus_path.read_text(encoding="utf-8")

    assert "SENTINEL:S_RESEARCH_SOL_COGNITION_PHENOTYPE_FOCUS_V1" in agreement
    assert focus_path.name in agreement
    assert focus_path.name in detailed
    assert "SENTINEL:RESEARCH_SOL_COGNITION_PHENOTYPE_FOCUS_CURRENT_V1" in focus
    assert "模型本身已有的 formation ability" in focus
    assert "substrate / continuity 放大的能力" in focus
    assert "过去 CognitionObject 真正教进去的能力" in focus
    assert "soft attractor 是当前主要 cognition debt" in focus
    assert "selective-invariance / counterexample world" in focus
    assert "不得再笼统结算“继承有效”或“continuity 有用”" in focus

    runtime = (REPO_ROOT / "services" / "research_sol" / "runtime.py").read_text(
        encoding="utf-8"
    )
    prompt_builder = runtime.split("def build_live_contact_prompt", maxsplit=1)[1].split(
        "def _main", maxsplit=1
    )[0]
    assert focus_path.name not in prompt_builder
    assert "soft attractor" not in prompt_builder.casefold()


def test_hot_s_contract_owns_event_driven_body_evolution_without_steering_sol() -> None:
    agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    detailed = (
        REPO_ROOT / "docs" / "tool_glue" / "S_CONTROL_TOWER_PRIMARY_MODE_CURRENT.md"
    ).read_text(encoding="utf-8")

    assert "SENTINEL:S_EVENT_DRIVEN_EVOLUTION_STEWARD_V1" in agreement
    assert "S-self、Research Sol 所消费的 research body" in agreement
    assert "cross-body machine substrate" in agreement
    assert "$steward-s-evolution" in agreement
    assert "不得再让用户负责点出单例、扩题、选仓、拼工具" in agreement
    assert "model-native formation ability" in agreement
    assert "substrate/continuity amplification" in agreement
    assert "prior CognitionObject shaping" in agreement
    assert "不是持续活动" in agreement
    assert "不是第四条 continuity loop" in agreement
    assert "复用下文既有的 S builder parent-frontier reentry" in agreement
    assert "不得建立 daemon、scheduler、固定测试或自动 wake" in agreement

    assert "S 的事件驱动 body-evolution stewardship" in detailed
    assert "control tower 规定实验与 effect 的物理边界" in detailed
    assert "phenotype CURRENT 提供一个可改写的观察尺" in detailed
    assert "用户无需再" in detailed
    assert "在模型/产品升级后 retire local compensation" in detailed
    assert "不新增第四条" in detailed
    assert "Research Sol `WAIT`" in detailed

    runtime = (REPO_ROOT / "services" / "research_sol" / "runtime.py").read_text(
        encoding="utf-8"
    )
    prompt_builder = runtime.split("def build_live_contact_prompt", maxsplit=1)[1].split(
        "def _main", maxsplit=1
    )[0]
    assert "steward-s-evolution" not in prompt_builder
    assert "S_EVENT_DRIVEN_EVOLUTION_STEWARD" not in prompt_builder
