# XINAO Seed Lab (`xinao-seed-lab`)

**GitHub:** `zhangyang7488-design/xinao-seed-lab`  
**Role:** Seed Cortex Phase0 施工仓 — 与母层档案仓 `nianhua` 分离  
**执行面:** Codex S @ `E:\XINAO_RESEARCH_WORKSPACES\S`（junction）  
**证据盘:** `D:\XINAO_RESEARCH_RUNTIME`  
**work_id:** `xinao_seed_cortex_phase0_20260701`

## 先读什么

```text
CODEX_S_L0.md
SEED_CORTEX_MUST_READ_FIRST.md
C:\Users\xx363\Desktop\新系统\AUTHORITY_READ_ORDER.txt
D:\XINAO_RESEARCH_RUNTIME\state\worker_assignment\xinao_seed_cortex_phase0_20260701.json
```

## 和 `nianhua` 的关系

| 仓库 | 用途 |
|------|------|
| **xinao-seed-lab**（本仓） | 新系统 / 333 / RootIntentLoop 真施工与绿堆代码 |
| **nianhua**（档案） | 旧母层 Blueprint；7/1 快照分支 `codex/prestage-pause-snapshot-20260701` 不默认合并 |

本地目录名可能仍为 `nianhua-new-route-active`（历史路径）；远端与语义身份已是 **xinao-seed-lab**。

**本仓清洗策略（2026-07-03）：** 孤儿历史、**仅 30 个跟踪文件**（绿堆 + 启动面 + 最少依赖）。旧 closure / Blueprint / legacy5d33 / 大索引 **已删除不进仓**。全历史备份在本地分支 `archive/full-history-20260703`。

## 默认主链（不是一轮 closure）

```text
用户中文 → Grok 保全双投递 → Codex S 大脑 → WORKER_ASSIGNMENT → worker 真干
循环：RootIntentLoop while · 宽度：frontier 动态并行 · 验收：D 盘 invoke + 阶段碑
```

**禁止**把 verifier PASS / 报告 / 旧 `docs/current` closure 当完成或默认停点。