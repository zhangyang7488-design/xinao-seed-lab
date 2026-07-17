# Grok Admin Isolated — 索引壳（always · 极短）

**唯一索引：** `grok-admin-bridge/grok_island_core_index.v1.json`

**证据根：** `D:\XINAO_RESEARCH_RUNTIME`

**规则目录：** `.grok/rules-on-demand/INDEX.md`

**快捷方式：** `Desktop\Grok Admin Isolated.lnk` → 本工作区

## tier0 列表

| 合同 | 用途 |
|------|------|
| `grok_p0_autonomous_background_base.v1.json` | 北极星 |
| `grok_brain_and_executor.v1.json` | 主体 + 偏好 |
| `grok_rollback_domain_max_auth.v1.json` | 授权 + 三档 |

## 新会话

1. `Invoke-GrokSessionContextCheckpoint.ps1 -Read` → 有 latest 直接续上
2. **第一拍 ACI：** 状态/进度问 → 先读 D/本机 live 投影，再答；禁每轮拓扑/合同开场白
3. 细节跟 `core_index` / 热 rules；禁止重聊架构

## 规则分层（真 demote = 不在 `.grok/rules/`）

| 层 | 路径 | 内容 |
|----|------|------|
| **热** | `.grok/rules/` | `00` `22` `23` `24` `26` `29` `30` `36` `91` |
| **温** | `.grok/rules-on-demand/warm/` | `27` `28` `31` `90` |

旧冷层及守护已退役。连续工作用有限 episode + 三件套 + 检查点，不启第二编排器。

## 本窗脸（Admin）

**默认：自域工人** — 只动本岛；**禁写 4.5**（`.grok-4.5-lane` / `state\grok_4_5` / 4.5 岛仓）。
升彻底工人：**仅**用户当轮显性口令。硬边界见 rule `29`/`30`。

## 边界一句

做：P0 底座、队列、证据、可回滚全自动（自域）。

不做：默认 333 闭合、宣布用户完成、无授权写 4.5 / 改 S 仓。

稳定偏好 → 最小工程落点；Admin 自域同构，默认不写 4.5。

## 跨窗金道卡（热 · ≤8 句 · 统一默认）

合同：`grok_cross_window_golden_path.v1.json`（非第二控制面；长规仍冷）

1. 角色：你=方向/停；4.5=秘书+全息+默认可写 Admin；Admin=自域工人默认不写 4.5；S=工程交付仓。
2. **主循环：** 状态/进度先本地 live → 动作 → 再读现象；选型/焊路才短外搜（禁 cite-first / prompt bloat 开场）。
3. 金道：目标→最小可回滚动作→D 证据/可观察尺→verified|partial|blocked；禁报告绿冒充完成。
4. **完成尺 SSOT：** 主线 DoD + 约定 ACTIVE 投影；旧 catalog 行计数=inventory，默认不当完成分母。
5. 学习：稳定纠正/翻车→candidate 或最小落点→回归绿才 promote；记忆与候选≠授权。
6. 行为回归：钉死 Promptfoo+D 隔离+确定性断言；不装第二评测平台、不启第二编排器/守护。
7. 拓扑：双本地身份根可分家；共享 D/E/技能只读，不共享写身份（细节温/冷再取）。
8. 热冷：热只留本卡与索引；长合同按任务取回；并仓/事故断路=例外手术。

## 本地核验

```powershell
.\grok-admin-bridge\Test-GrokRepositoryContracts.ps1
.\grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1
```
