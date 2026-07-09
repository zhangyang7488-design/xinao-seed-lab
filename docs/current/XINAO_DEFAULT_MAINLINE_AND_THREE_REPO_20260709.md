# XINAO 默认主路与三仓边界（S 仓文档 · 2026-07-09）

**本文件在 S 仓。** 完整人读规格：`D:\XINAO_RESEARCH_RUNTIME\specs\xinao_three_repo_default_mainline_20260709.md`

## S 仓是什么

**333 工程默认主路**（唯一生产 compose）：

- 入口：`scripts/Start-XinaoBaseCompose.ps1` / `docker-compose.yml`（project `xinao-base`）
- Worker：`docker/xinao-worker/Dockerfile` → `xinao-worker`
  - 命令：`python -m services.agent_runtime.integrated_bus_worker_daemon`
  - 队列：`xinao-integrated-langgraph-plugin-queue`
  - 烘焙：pytest / instructor / fastmcp；镜像内 git；COPY tests
- Mature 挂载：`XINAO_EXTERNAL_MATURE_HOST` → `/external_mature/official`
- Gateway：容器内 `http://litellm:4000/v1`
- 认领 SDK：`services.agent_runtime.task_entry_claim`

**不是：** Grok 岛脚本仓库；不是 4.5 身份仓。

## 不在本仓、但薄绑本仓的

| 谁 | 路径 | 做什么 |
|----|------|--------|
| Grok Admin 岛 | `...\Grok_Admin_Isolated\workspace\grok-admin-bridge` | ROI/自转/ClaimDurable 调本仓 compose |
| Grok 4.5 岛 | `...\workspace-grok-4.5-island` | 对话身份隔离；合同语义可读 Admin |

## 禁止

- 把 Admin 工作树 `git push` 到本仓 `origin`（历史无关，会炸）
- 把 Grok 巡检队列当成 333 Temporal owner
- 用报告绿宣布用户完成 / P0 闭合

## 收口证据

- bus validation 绿：`D:\XINAO_RESEARCH_RUNTIME\readback\integrated_bus_*.json`
- 三仓规格：`D:\XINAO_RESEARCH_RUNTIME\specs\xinao_three_repo_default_mainline_20260709.md`
