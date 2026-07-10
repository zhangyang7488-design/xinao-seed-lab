# Codex 本机能力面薄绑定审计（2026-07-10）

## 结论

当前 canonical `CODEX_HOME` 是 `C:\Users\xx363\.codex`。新 Codex 窗口默认加载全局工作约定、D 盘态势检查点与上下文目录，按任务使用原生工具、并行子代理、浏览器/桌面能力、插件、MCP、原生 Memories 和纯本地 Mem0。旧 S/333/Temporal/CLEAN 不再作为默认主链，也没有新建守护进程、开机服务或第二套编排平台。

这里的“强模式”不是强制输出 Chain-of-Thought、把全部历史塞进上下文、无限自我批判或无条件多代理。它是：高推理预算、任务模式路由、即时检索、独立工作才并行、真实证据门、明确终止条件、可恢复事件账本和分层记忆。

## 智力保护与动态收益

能力可用性和能力调用被明确分开：所有已验证能力在新窗口保持可用，这是强默认；是否调用某个工具、技能、模型或更多代理，则按任务匹配、推理质量、证据和速度收益，综合风险、延迟、成本与协作摩擦动态选择。这里不设置伪精确分数、固定并行度或强制工具序列。

用户权威、安全、秘密、外部副作用范围和真实结果门是硬护栏；护栏内的流程只是可修正策略。任务账本和技能不能升级成第二套控制器，也不能为了遵守清单或节省 token 降低推理质量、求真能力与改变路线的自由。

在对象已经明确时，“收口”默认表示：删除范围内可证明无用的残留，保留有效成果，完成相称验证，并在当轮仓库工作流已获授权时提交、推送和合并。它不是对无关部署、身份操作、秘密、广泛删除或永久运行的空白授权。

## 从成熟开源 Agent 借来的机制

| 成熟来源 | 采用的机制 | 本机薄绑定 |
|---|---|---|
| OpenHands、mini-SWE-agent | 原子步骤、追加事件、步数/时间上限、卡住检测 | `verified-agent-loop` 的事件账本、有限重试和四态完成 |
| LangGraph | checkpoint、fan-out/fan-in、幂等恢复 | 使用 D 盘 JSON/JSONL 账本，不安装第二个图运行时 |
| OpenAI Agents SDK、AutoGen | manager/workers、typed handoff、HITL、显式终止 | 映射到 Codex 原生子代理、单写者和独立 verifier |
| PydanticAI Evals | Case/Evaluator 与确定性断言 | 仓库测试和有界 Promptfoo app-server 评测 |
| Aider | ask/code 模式、按预算加载 repo map | dialogue/plan_only/bounded_task/continuous 路由与 JIT 上下文 |
| Letta、CoALA | 小核心 + 可检索档案、记忆分层 | 原生 Memories + D 盘 checkpoint/catalog + 本地 Mem0 |
| Magentic-UI、UFO | 共同规划、人工接管、分级桌面操作 | API/CLI 优先，其次 DOM/UIA，最后视觉操作 |
| Playwright CLI | 低 token 的结构化浏览器操作 | canonical `playwright-cli` skill |

没有复制这些项目的整个平台、守护进程、身份、凭据、自动提交或无限循环。先把机制映射到 Codex 原生 primitive；只有原生表面缺失时才保留薄适配器。

## 已落地能力面

### Canonical 新窗口

- 配置：`C:\Users\xx363\.codex\config.toml`。
- 模型：`gpt-5.6-sol`，推理强度 `ultra`；不伪造或暴露隐藏 Chain-of-Thought，只给可核验的假设、证据和结论。
- Plan 模式固定 `xhigh`；官方配置没有受支持的全局 `temperature` 键，因此不写无效参数，以任务模式、模型 profile 和验收标准区分创造性与精确性。
- 40/40 插件 enabled；38 个实际 feature flags 为 true。
- 11 个可见 MCP 条目；旧 `xinao` discovery MCP 已从 canonical 和旧 seed 配置删除。
- Apps 默认 enabled，包含 destructive/open-world 工具并使用 `approve` 模式；权限仍受当前用户请求范围、全局协议和工具自身登录态约束。
- 全局协议：`C:\Users\xx363\.codex\AGENTS.md`。
- 每窗 SessionStart：只注入小 checkpoint 与目录索引，材料按任务即时加载。
- 技能：`verified-agent-loop`、`playwright-cli`。
- 本地 profile：`local-ollama=qwen2.5-coder:7b/high`、`local-general=qwen3:8b/none`、`local-reasoning=qwen3:8b/high`。三者通过 D 盘 catalog 明确指向 `127.0.0.1:11434/v1`，避免本机 `localhost` 与 IPv4 loopback 落到不同 Ollama 监听面的故障。

### 分层上下文与记忆

- 人类材料根：`C:\Users\xx363\Desktop\主线`，终验时为六份材料；目录是入口，不把某份文本升格为不可变权威。三份长文在收口期间被外部活进程按“用户要求恢复/勿自动删除”重新写回，因此保留并纳入按需目录，未再次强删。
- 态势岛：`D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island`。
- `session_checkpoint.json` 负责短恢复摘要，`context_catalog.json` 负责按关键词发现材料，`runs/` 负责机器可核验的任务事件和证据。
- 原生 Memories 的生成和使用默认开启。
- 本地长期记忆位于 `D:\XINAO_RESEARCH_RUNTIME\state\mem0`，仅用 Mem0 OSS、loopback Ollama、embedded Qdrant/history；托管 Mem0 和 telemetry 关闭。
- 本地记忆按 user/project/scope 隔离；支持 semantic/episodic/procedural、confidence、expiry、supersedes、source、sensitivity 和只读历史。
- 多窗口通过 D 盘跨进程锁串行打开 embedded Qdrant；忙时明确返回 `memory_busy`，不让窗口假死。记忆召回内容永远只是上下文，不是授权或任务权威。
- FastMCP stdio 在启动事件循环前只预载 Mem0/Qdrant/NumPy 依赖，不打开存储；真实协议 `list` 为 0.214 秒，canonical 只读新进程也已 started→completed。

### 工具与人机操作

- Windows、Chrome、Computer Use、Node REPL、隔离 Chrome DevTools、Playwright CLI。
- Codebase Memory MCP 0.9.0，最终合并后的精简仓库图为 366 nodes / 1,100 edges，状态 ready。
- OpenAI Developer Docs、GitHub、Cloudflare、Sites、LaTeX、Visualize 和 artifact plugins；远程能力仍受真实登录态约束。
- 桌面任务采用 API/CLI → DOM/Playwright/CDP → UI Automation → 视觉坐标的降级次序，兼顾稳定性、可接管性与 token 成本。

## 清理边界

- 仓库旧 `apps/contracts/docker/materials/policies/src/services/agent_runtime/services/codex_activator` 及旧 hardmode/Temporal/333 脚本已删除；按 `uv.lock` 的 `[[package]]` 条目计数，依赖锁从远端基准的 509 缩到 174 packages。
- 已删除可证明是旧副本、缓存、孤儿 runtime、废弃 Codex home、旧 scheduled task、无用 node_modules 与关闭的超大 debug logs。
- 保留当前 Git worktree、D 盘 Mem0/态势岛、canonical `.codex`、仍有活引用的进程/日志，以及无法证明重复的历史会话和备份。记忆与唯一历史不按“垃圾”处理。
- 当前已打开的旧会话不会热切换 `CODEX_HOME`；新窗口使用 canonical home。旧 seed 中的唯一历史要在所有旧窗口关闭后做离线去重迁移，不能在线粗暴删除。
- 收口时仍有 Grok 子进程引用已退休的 `services/mcp/xinao_mcp_server.py`；源码从新主路删除，但不强杀活进程。Grok 关闭后该旧进程不能重启，届时再复核其 lane skills 与本地 broker token 轮换。

### 旧机制研究材料的可恢复索引

以下五份材料有研究溯源价值，但包含旧胶水层叙事，不恢复为当前执行面。它们完整保留在合并基准 `28aa6ffecbf5c019176a9f3882960a6d88b25aea` 的 Git 历史中，可用 `git show 28aa6ff:<path>` 精确读取；新窗口只在任务明确需要历史机制证据时检索。

| 历史路径 | Blob SHA |
|---|---|
| `materials/authority_glue/00_先发这个_阅读顺序.txt` | `696122984c63e18344d5699e2e13578d8c4e6f41` |
| `materials/authority_glue/XINAO_外部薄胶开焊总图_20260708.txt` | `3c55af9cdee6ed922100ac3f046450b1d0036ed5` |
| `materials/authority_glue/glue_mature_repo_registry.v1.json` | `5b4fb1722a4cff5daee6016599bec77a23221bf2` |
| `materials/authority_glue/XINAO_胶水层调研结果_Grok_20260708.md` | `e064feea0c802111d9195de2b5aa2c50a1fcdaf3` |
| `materials/authority_glue/overnight_glue_items.v1.json` | `fae6eac13ac63e749ba238395e8d5abc897c6aef` |

## 验证

- canonical strict doctor：17 ok / 0 warn / 0 fail。
- plugins：40 installed / 40 enabled；effective features：38 true。
- Situation Island 自测：READY；无 Codex 岛 Windows 开机自启。
- 本地记忆：36 个定向测试、四进程并发 smoke、生命周期、历史和真实 stdio/canonical smoke 通过。
- 仓库：Ruff lint、Ruff format、`uv lock --check`、`git diff --check` 通过；完整 pytest 49/49 通过。
- 最终 Promptfoo app-server 评测：1/1 case、2/2 assertions；验证只读命令执行、结构化输出、thread/turn trace 与 token ledger。
- `verified-agent-loop` 初始化、缺证据拒绝完成、补齐证据后完成、结构验证均通过。
- 新 canonical 临时进程加载全局与项目 sentinel 后，能力默认可用、动态激活、“收口”动作和 `fixed_controller=false` 共 11 项断言通过。
- GitHub PR #8 已 squash merge 为 `d0cfd620d483708c16a772f14ecf25c663eac62b`；Ubuntu 3.12、Windows 3.11 与 CodeQL analyze 全部成功，远端树与本地验收树 SHA 一致。
- 代码图最终重建后 366 nodes / 1,100 edges，越界根仍拒绝。

## 主要公开依据

- OpenAI, *A practical guide to building agents*: https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/
- Anthropic, *Building effective agents*: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, *Effective context engineering for AI agents*: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, *Demystifying evals for AI agents*: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- OpenHands: https://github.com/OpenHands/OpenHands
- mini-SWE-agent: https://github.com/SWE-agent/mini-swe-agent
- LangGraph: https://github.com/langchain-ai/langgraph
- OpenAI Agents handoffs/HITL: https://openai.github.io/openai-agents-python/handoffs/ and https://openai.github.io/openai-agents-python/human_in_the_loop/
- PydanticAI: https://github.com/pydantic/pydantic-ai
- Letta: https://github.com/letta-ai/letta
- Magentic-UI: https://github.com/microsoft/magentic-ui
- UFO: https://github.com/microsoft/UFO
- Playwright MCP/CLI: https://github.com/microsoft/playwright-mcp
- Reflexion: https://arxiv.org/abs/2303.11366
- CoALA: https://arxiv.org/abs/2309.02427

配置、插件、hook 和全局规则以新窗口加载结果为准；状态快照不是永久权威。
