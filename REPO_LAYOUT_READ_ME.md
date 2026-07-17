# 4.5 岛 · 仓库布局（只读真相指针）

**本窗口 = 对话 / 规划脑 · 身份隔离。不是 333 工程仓，也不是 Admin 脚本真相源。**

## 三仓

| 角色 | 路径 |
|------|------|
| **S · 333 默认主路** | `E:\XINAO_RESEARCH_WORKSPACES\S` |
| **Admin · Grok 岛运维真相** | `D:\Grok_Admin_Isolated\workspace\grok-admin-bridge` |
| **本岛 · 4.5** | 本目录：agent_id / lane MEMORY / session 隔离 |

规格全文：`D:\XINAO_RESEARCH_RUNTIME\specs\xinao_three_repo_default_mainline_20260709.md`

## 本岛 `grok-admin-bridge/` 角色

- 本岛是 **Grok 4.5 endpoint identity、隔离合同和 canary** 的唯一写面，不是被动镜像。
- 共享 bounded WorkerPool 的实现与 Composer 入口仍由 **Admin** 工作区拥有；本岛只保存 canonical 指针并做真实调用验收。
- 4.5 紧耦合合同、规则和探针在本岛修改；共享池或 Admin 身份修改回 Admin，禁止复制第二套实现。

## 禁止

- 把本岛当第二套 RunNext/Claim 源去「合并进 S」
- 写 Admin `task_queue` / Admin checkpoint `latest`（跨窗污染）
- 宣布 P0 闭合
