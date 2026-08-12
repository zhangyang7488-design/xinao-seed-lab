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
