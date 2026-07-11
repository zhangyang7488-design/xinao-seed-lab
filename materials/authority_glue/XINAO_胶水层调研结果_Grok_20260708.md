# XINAO 胶水层调研结果 — Grok (xAI) — 2026-07-08

**SENTINEL 参考**: XINAO_GLUE_LAYER_OSS_RESEARCH_BRIEF_20260708
**调研范围**: 仅胶水层 (adapter / SDK wrapper / CLI / sidecar / bridge / schema / git-CI 薄绑)，**不替代** Temporal / LangGraph / LiteLLM 核心。
**环境假设**: Windows + Python 3.12 + E:\XINAO_RESEARCH_WORKSPACES\S 执行仓 + D:\XINAO_RESEARCH_RUNTIME 证据 (ledger / readback / zh)
**方法**: 每个推荐必须回答“去掉这个胶水，哪一节接不上？”；所有均为 glue（非 core 替代）；优先高 stars + 最近活跃 + Py3.12/Windows 友好 + permissive license；薄绑工作量控制在接缝（≤5 项改动）。

---

## 总览表

| 层 | 推荐胶水 #1 | URL | glue_role 一句话 | 薄绑工作量(小/中) | 不推荐原因(若有) |
|----|-------------|-----|------------------|-------------------|------------------|
| L0 | microsoft/markitdown | https://github.com/microsoft/markitdown | 多格式文档 (PDF/Office/txt/md/json) → 统一 Markdown + 结构化文本 intake 胶水 | 小 | - |
| L1 | pydantic | https://github.com/pydantic/pydantic | 结构化任务模型定义 + JSON schema 校验 + LangGraph plan node I/O 胶水 | 小 | - |
| L2 | GitPython | https://github.com/gitpython-developers/GitPython | 本地 repo 状态观察 (status/diff) + GitOps reconcile + commit/push 自动化胶水 | 小-中 | - |
| L3 | OpenHands | https://github.com/OpenHands/OpenHands | 执行平面 sandbox / worker runtime 胶水 (Temporal activity 真 invoke code task) | 中 | Full platform 风险：只薄绑 execution 部分，严禁替换 LangGraph supervisor 或 Temporal owner |
| L4 | tavily-python | https://github.com/tavily-ai/tavily-python | 外部成熟搜索 sidecar (Tavily AI-optimized API) | 小 | - |
| L5 | langfuse-python (OTEL) | https://github.com/langfuse/langfuse-python | trace / 生成证据 → Langfuse (支持 LiteLLM) + report→readback md 辅助胶水 | 小 | - |
| L6 | temporalio/samples-python + LangGraph 官方 examples | https://github.com/temporalio/samples-python | Temporal retry/saga/compensation 官方 pattern + LangGraph critic/reflexion 薄绑 | 小 | - |
| L7 | mlflow (examples) + optuna | https://github.com/mlflow/mlflow | 实验 tracking / promotion gate 社区组件参考 (无单一成品) | deferred (小) | 无单一成熟“自进化闭环”成品，只列可薄绑组件 |
| L8 | jinja2 | https://github.com/pallets/jinja | Markdown 报告模板引擎 + LiteLLM 路由中文摘要 sidecar 胶水 | 小 | - |

**L3 备选对比**（选 OpenHands 为主推）：
- SWE-agent (https://github.com/SWE-agent/SWE-agent, MIT, 19.7k stars, 极活跃)：更偏 SWE-bench/issue fixing，CLI 成熟，可作 code-heavy worker 备选，薄绑工作量类似但领域更窄。
- e2b code-interpreter (https://github.com/e2b-dev/code-interpreter, Apache-2.0, ~2.4k stars)：最轻量纯 sandbox SDK (Sandbox.create + run_code)，适合 cheap lane 快速任务，cloud 或自建模板；Windows host 需 Docker/ infra 额外考虑。

---

## 分_layer 详表

### L0 材料池 / 意图摄入胶水
**推荐：microsoft/markitdown**

- **URL**: https://github.com/microsoft/markitdown
- **license**: MIT
- **最近活跃度**: 最后 commit 2026-05 (2 个月前)，累计 ~164k stars，极受欢迎的轻量工具
- **glue_role**: 多格式文档（PDF、Word、Excel、PPT、txt、md、json、HTML 等）→ 统一 clean Markdown + 结构化文本（带 metadata）的 intake 胶水。解决“材料池”从桌面/新系统/口述 → 可被后台读的 task_package 问题。去掉它，L0 多格式 intake 就得手搓解析器或依赖重型 CMS。
- **thin_bind_surface** (≤5 条):
  1. pip install 'markitdown[all]' (或按需 extras)
  2. 在 Temporal activity 或 CLI wrapper 中调用 `from markitdown import MarkItDown; md = MarkItDown().convert(path)`
  3. 输出统一 .md + frontmatter yaml (title/source/hash) → 写入 D:\XINAO_RESEARCH_RUNTIME\pool\
  4. 简单 manifest.json 追加 entry（与现有 capabilities/manifest 对齐）
  5. 可选 watchdog 监听桌面指定文件夹触发 intake（额外小 glue）
- **do_not_fork**: 不要复制 markitdown 内部 converter 逻辑或加新 format parser；只用其 CLI/lib 接口。
- **integration_hook**: Temporal Activity (或 LangGraph tool node) 调用 markitdown → 产出 task_package.json 喂给 L1 Pydantic 模型。
- **evidence_output**: D:\XINAO_RESEARCH_RUNTIME\pool\YYYYMMDD_HHMMSS_<hash>.md + intake_manifest.jsonl（对齐 readback 习惯）
- **risks**:
  - License MIT，完全 permissive。
  - Py 3.12 + Windows 友好（纯 Python + 可选依赖如 pdfplumber 等）。
  - PDF 转换质量因文档复杂而异（官方已知），但对研究材料足够；无 Docker 强制依赖。
  - 维护活跃（Microsoft 出品）。

**备选轻量**（若需数据包）：frictionlessdata/frictionless-py (CLI + package validation) 或 ResearchObject/ro-crate-py（RO-Crate 元数据）。

### L1 文本→意图任务 / 任务分解胶水
**推荐：pydantic ( + jsonschema 辅助)**

- **URL**: https://github.com/pydantic/pydantic
- **license**: MIT
- **最近活跃度**: 极高活跃，v2 成熟，广泛用于生产结构化输出
- **glue_role**: 定义 TaskPackage / PlanStep / EvidenceRef 等 Pydantic BaseModel + field_validator / model_validator 做 JSON schema 校验和 coercion。LangGraph plan node 的输入输出严格用这些模型序列化。去掉它，L1 结构化任务分解和 schema 校验就得手写或用脆弱的 dict/json。
- **thin_bind_surface**:
  1. 定义核心 models (TaskPackage, SubTask, EvidencePointer 等) 在 shared/ 模块
  2. 在 LangGraph plan node 使用 `model_validate_json` 或 `instructor` 风格但只用 LiteLLM + Pydantic
  3. 输出 validated plan → JSON/YAML 序列化给 Temporal workflow input
  4. 可选 jsonschema 包做额外 runtime 校验（极薄）
- **do_not_fork**: 不要手搓 JSON schema 或 validator 逻辑；用 Pydantic v2 成熟功能。
- **integration_hook**: LangGraph `@tool` 或 plan node 直接返回 Pydantic model instance → Temporal signal/ start workflow with model.model_dump()
- **evidence_output**: D:\XINAO_RESEARCH_RUNTIME\plans\plan_<id>.validated.json (带 schema version)
- **risks**: MIT，Py 3.12 完美支持，Windows 无问题。极稳定，无额外 infra。

**备选/补充**: networkx (https://github.com/networkx/networkx) 用于 DAG 依赖图序列化（若 plan 需要显式 dependency graph）。

### L2 控制环 / reconcile 胶水
**推荐 #1: GitPython (本地 repo + evidence 观察)**

- **URL**: https://github.com/gitpython-developers/GitPython
- **license**: BSD-3-Clause (permissive)
- **最近活跃度**: 稳定维护，成熟
- **glue_role**: 观察本地 E:\XINAO... repo 状态 (git status, diff, log) + 对比 D: evidence 中的 desired state / manifest → 产生 reconcile 信号或 action plan。LangGraph supervisor 模式可在此基础上做 state machine 决策。去掉它，L2 “观察本地证据 vs 期望态” 就无法自动化，控制环断裂。
- **thin_bind_surface**:
  1. `from git import Repo; repo = Repo(path)`
  2. 封装 `get_local_state()` / `compute_diff_vs_evidence(ledger_path)` 返回 structured diff
  3. 在 LangGraph reconcile node 或 Temporal activity 中调用
  4. 产生 action (commit message, branch, signal)
  5. 可选结合 watchdog 做文件变更触发（极薄）
- **do_not_fork**: 不要重写 git 底层逻辑或做 custom vcs；只薄 wrapper。
- **integration_hook**: LangGraph supervisor node 调用 GitPython 获取 state → 决定是否派发 worker 或 self-fix；Temporal activity 做实际 git 操作。
- **evidence_output**: D:\XINAO_RESEARCH_RUNTIME\reconcile\reconcile_<id>.jsonl (state snapshot + diff + decision)
- **risks**: BSD，纯 Python，Windows 完美支持 (无编译依赖问题)。维护稳定。

**推荐 #2 / 补充 (LangGraph supervisor 薄绑点)**: langchain-ai/langgraph 官方 supervisor pattern（或 langgraph-supervisor-py 仅作迁移参考）。现在官方推荐直接用 tool-calling + create_supervisor 模式在我们的 graph 里实现 supervisor。薄绑工作量极小：只在现有 LangGraph graph 中加 supervisor node + handoff tools。不要 fork 整个 supervisor 库。

**任务队列建议**: 优先用 **Temporal 自身 task queues + signals**（已支持 priority/ sticky 等）。若需跨 worker 外部 priority queue，再考虑 rq (Redis Queue) + redis-py 作为极薄 glue。不要引入独立重型队列系统。

### L3 执行平面胶水 (Temporal ↔ Worker 运行时)
**主推：OpenHands**

- **URL**: https://github.com/OpenHands/OpenHands
- **license**: Core OSS 部分 permissive（相关项目 MIT，enterprise/ 子目录不同；使用前确认 LICENSE）
- **最近活跃度**: 极高（数小时前有 commit），79.7k+ stars
- **glue_role**: 作为**执行沙箱 / worker runtime** 胶水。Temporal activity 把 plan task (code edit / run / test) 派发给 OpenHands sandbox 执行真 invoke，捕获 trajectory / changed files / logs。去掉它，L3 “真执行 + 沙箱隔离 + git 交互” 就得手搓 subprocess + Docker harness，容易出安全/状态问题。**严禁** 把 OpenHands 当全脑替换 LangGraph planner 或 Temporal workflow owner。
- **thin_bind_surface** (中等工作量):
  1. Docker Desktop (Windows) 安装 + volume 映射 E: 和 D:（或 WSL2 backend 推荐）
  2. Temporal activity 中用 subprocess 或 OpenHands server API/CLI 启动 agent 任务 (传 task JSON + workspace path)
  3. 封装 output parser：trajectory.jsonl + final_patch + exit_code → 结构化 evidence
  4. GitPython (或 gh wrapper) 在执行后做 commit / push / branch（见 L2）
  5. Heartbeat + timeout + cancellation 包装（Temporal activity 最佳实践）
- **do_not_fork**: 不要复制 OpenHands 内部 agent loop、prompt engineering 或 evaluation 逻辑；只用其 sandbox execution 能力。
- **integration_hook**:
  ```python
  @activity.defn
  async def run_in_openhands(task: dict) -> dict:
      # 调用 OpenHands CLI/server with task["instruction"], task["workspace"]
      result = subprocess... or requests to localhost:...
      write_evidence(result)  # D: + Langfuse
      return {"status": ..., "evidence_ref": ...}
  ```
- **evidence_output**: D:\XINAO_RESEARCH_RUNTIME\executions\exec_<id>\ (trajectory.jsonl, diff.patch, logs, screenshots if any) + Langfuse trace
- **risks**:
  - Docker 依赖（Windows 需 Docker Desktop，volume 权限需注意）。
  - License：core  permissive，但 enterprise 功能商业；我们只用 OSS execution 部分。
  - Py 3.12：项目 Python 重度，理论兼容，实测建议用官方 Docker image。
  - 资源占用：完整 agent 较重，适合复杂任务；简单任务可用 e2b 备选。
  - 维护极活跃，但作为 glue 要控制 scope（只 execution）。

**备选**:
- **SWE-agent**: MIT, 19.7k stars, 极活跃。最近 commit 数小时前。CLI 成熟，适合 repo issue/code fix 场景。薄绑类似，领域更聚焦 SWE。
- **e2b**: Apache-2.0, 轻量 SDK (`Sandbox.create().run_code()`), 适合 cheap/fast lane。Cloud 或自建模板。Windows host 需额外 infra 考虑。

**subprocess / JSONL stream 聚合**: 用标准库 `subprocess` + `logging` + `jsonlines` 或 `tenacity` 重试 wrapper 即可（极成熟，无需新 repo）。

**Git 操作胶水**: 直接用上面 L2 的 GitPython（commit/push/rollback 自动化）。

**MCP client**: 若指 E2B MCP 或类似 tool protocol，e2b 已提供相关集成；否则用标准 tool calling via LiteLLM + activity。暂不额外推荐重型 MCP SDK。

### L4 外部成熟搜索 / 对照本地胶水
**推荐：tavily-python**

- **URL**: https://github.com/tavily-ai/tavily-python
- **license**: MIT
- **最近活跃度**: 活跃，1.3k+ stars
- **glue_role**: 外部搜索 sidecar。LiteLLM 或 Temporal activity / LangGraph tool node 调用 Tavily 做 web search / extract / research，补充本地证据。去掉它，L4 外部知识获取就得手搓 requests + parse 或用不优化的通用 search。
- **thin_bind_surface**:
  1. pip install tavily-python + API key (env)
  2. 封装 `tavily_search(query, search_depth=...)` → 返回 structured results
  3. 在 LangGraph retrieval node 或 research activity 中调用
  4. 结果写入 evidence (带 source url + snippet + score)
- **do_not_fork**: 不要实现自己的 crawler 或 ranking；只用 Tavily 成熟 API。
- **integration_hook**: LangGraph tool 或 Temporal activity 调用 SDK → 结果 feed 给 supervisor 或 worker。
- **evidence_output**: D:\XINAO_RESEARCH_RUNTIME\search\search_<id>.jsonl (query + results + timestamp)
- **risks**: MIT，纯 Python client。需 API key（免费 tier 有额度限制）。Windows/Py3.12 无问题。备选自托管：SearXNG (更重 infra)。

**clone 外部 repo 只读分析胶水**: tiged/tiged (https://github.com/tiged/tiged, degit 继任者) 或 git sparse-checkout + subprocess。极薄。

**许可证/依赖扫描 (可选)**: raimon49/pip-licenses (CLI 简单，输出 JSON/License 报告到 evidence)。

### L5 验证 / 收尾胶水 (真 invoke，非 PASS 墙)
**推荐：langfuse-python (OTEL) + 辅助 report 工具**

- **URL**: https://github.com/langfuse/langfuse-python (主平台 https://github.com/langfuse/langfuse)
- **license**: MIT (ee 目录除外)
- **最近活跃度**: 活跃，OTEL v3 SDK 新发布
- **glue_role**: 把 LLM 调用、agent 步骤、worker 执行包装成 OTEL trace / span → 发送到 Langfuse 作为结构化证据（可 self-host）。同时支持 LiteLLM 直接集成。去掉它，L5 “真执行验证 + 可观测证据” 就只能靠简单 log 或 PASS 墙，无法做长期 readback / 审计。
- **thin_bind_surface**:
  1. pip install langfuse + OTEL deps
  2. 初始化 client (public/secret key or self-host endpoint)
  3. 用 `@observe()` decorator 或 low-level start_span 包装关键 activity / LLM call
  4. 在 Temporal activity 结束时 flush trace + 更新 evidence metadata
  5. 可选结合 pytest-json-report 或 coverage + 简单脚本转 md 追加到 readback
- **do_not_fork**: 不要自己实现 tracing backend；用 Langfuse 成熟 OTEL 集成。
- **integration_hook**: Temporal activity / LangGraph node 里加 observe 装饰器；LiteLLM callback 也可直接指向 Langfuse。
- **evidence_output**: Langfuse dashboard + D:\XINAO_RESEARCH_RUNTIME\traces\trace_<id>.json (或直接用 Langfuse query API 导出)；同时写 human-readable md summary 到 readback/
- **risks**: MIT，Py3.12 支持好。self-host 需要 Postgres + ClickHouse 等（或用 cloud）。Windows 客户端无问题。完美对齐“trace 当证据”需求。

**其他辅助**:
- schemathesis (https://github.com/schemathesis/schemathesis)：契约测试薄绑到 API activity（若有）。
- diff-cover + coverage.py → md 报告（成熟脚本 glue）。

### L6 失败自修复胶水 (环内换路，非 verifier 马拉松)
**推荐组合（官方 pattern）**:

- **Temporal**: https://github.com/temporalio/samples-python （官方 retry, saga, compensation, continue_as_new, signal 等 examples）。在我们的 workflow 中直接用 `@retry` policy + compensation activity。薄绑工作量极小：配置 retry policy + 定义 compensation activity。
- **LangGraph**: langchain-ai/langgraph 官方 examples / tutorials 中的 reflection / critic / reflexion agent 模式。在 supervisor graph 中加 critic node + conditional edge 做 alternate strategy routing。不要手搓新 verifier。
- **alternate strategy routing**: LangGraph 内置 conditional edges + state 即可；辅助可用 tenacity (https://github.com/jd/tenacity) 做 Python 重试策略。
- **自动 rollback**: GitPython + `git checkout -b fix/xxx` + revert commit 脚本（可选副产品，L2 已覆盖）。

**glue_role**: 当 worker 执行失败或 evidence 显示不达标时，Temporal/LangGraph 环内自动换路重试（不同 model lane、不同 strategy、或 human-in-loop signal）。去掉这些官方 pattern，就得自己发明 saga/retry 逻辑，容易出状态不一致 bug。

**thin_bind_surface**: 在现有 Temporal workflow definition 和 LangGraph graph 中加入 retry + critic conditional edge + compensation activity（≤ 新增 2-3 个 node/activity）。

**evidence_output**: 失败轨迹 + retry decision 写入 D: ledger + Langfuse trace（带 retry_count, alternate_strategy）。

**risks**: 官方 examples，license 宽松，Py3.12 支持。无额外依赖风险。

### L7 长期自进化胶水 (第 5 条 · 次要但列清单)
**明确标注**：**无单一成熟“自进化闭环”成品仓库**。只列可薄绑的 tracking / optimization 组件，供未来 L7 promotion gate 使用。

- **MLflow** (https://github.com/mlflow/mlflow)：实验 tracking + model registry + CI 集成最小 official examples。适合记录 strategy trial → metric → promotion decision。
- **Optuna** (https://github.com/optuna/optuna)：超参/策略优化框架，可与 MLflow 结合做 promotion gate 逻辑。
- 社区模式参考：TrialLedger 类设计（对标开源 experiment tracking + gate 模式），但不推荐任何单一“自进化平台”作为 core glue。

**deferred**：等核心 L0-L6 稳定后再评估具体 promotion 实现（人工 review gate 或 auto metric gate）。

### L8 中文 readback / 用户面胶水 (cockpit 非执行)
**推荐：jinja2 + LiteLLM 路由**

- **URL**: https://github.com/pallets/jinja (Jinja2)
- **license**: BSD-3-Clause
- **glue_role**: Markdown 报告 / 中文摘要模板引擎。machine state / evidence / execution result → 用 LiteLLM (经由核心 LiteLLM) 路由生成中文可读摘要 + Jinja 渲染成结构化 md 报告。去掉它，用户面 cockpit 就得手搓字符串模板或依赖重型静态站点生成器。
- **thin_bind_surface**:
  1. pip install jinja2
  2. 定义 templates/ 目录下 report_zh.md.j2 (含 frontmatter, sections for plan/execution/evidence)
  3. 在 L5/L6 收尾 activity 中：调用 LiteLLM (model=cheap lane) 做 “将以下 evidence 总结成中文结构化摘要” → 填入 Jinja context → 渲染输出
  4. 写出 D:\XINAO_RESEARCH_RUNTIME\readback\中文摘要_<date>.md + index.md
- **do_not_fork**: 不要自己写模板引擎或 summarization 模型；只用 Jinja + 现有 LiteLLM。
- **integration_hook**: Temporal activity 或 LangGraph final node 调用 LiteLLM + Jinja render → evidence write。
- **evidence_output**: D:\XINAO_RESEARCH_RUNTIME\readback\ (中文_*.md + machine_*.jsonl)；cockpit 通过 Grok 外脑或简单文件 watcher 展示。
- **risks**: BSD，纯 Python，Windows/Py3.12 完美。无新模型调用（复用 LiteLLM）。

---

## 集成拓扑简图 (ASCII)

```
用户文本 / 桌面材料 / 口述
          │
          ▼
[L0] markitdown intake → task_package.md + manifest.jsonl
          │
          ▼
[L1] Pydantic TaskPackage / PlanStep schema validate
          │
          ▼
LangGraph Plan Node (supervisor pattern)
          │
          ▼
Temporal Workflow (core owner, durable, retry, event history)
   ├── L2 reconcile (GitPython observe local repo + D: evidence desired state)
   │         │
   │         ▼
   │   decide: dispatch / self-fix / escalate
   │
   ├── L3 activity: invoke OpenHands (or SWE-agent / e2b)
   │         │   (subprocess / API + workspace=E:\S)
   │         ▼
   │   worker 执行 (code edit / test / run)
   │         │
   │         ▼
   │   GitPython commit / push + evidence capture
   │         │
   │         ▼
   │   L5 Langfuse OTEL trace + report → D: readback
   │
   └── if fail / evidence not pass:
         L6 Temporal retry policy + LangGraph critic/reflexion loop
               (alternate strategy / different lane / human signal)
                     │
                     ▼
               ring 内重试 or compensation

最终收尾 → L8 Jinja2 + LiteLLM 中文摘要 sidecar → D:\readback\中文_*.md
          │
          ▼
用户 cockpit (Grok 外脑展示，不直接 ingress)
```

**核心流向**: 材料池 → 结构化意图 → LangGraph 计划环 → Temporal  durable 执行环 (L2/L3/L5/L6) → 证据 readback → 中文 cockpit。**所有 glue 只在接缝改动**。

---

## 明确不选的仓库及原因（≥5 条，防安全模板）

1. **CrewAI / AutoGen 全栈 agent 平台**：试图自己做 orchestrator + memory + execution，与 Temporal (durable owner) + LangGraph (内层策略 supervisor) 严重重叠。容易变成又一版“焊死在 pytest/PASS 的安全模板”，违反“不要默认 CrewAI/AutoGPT 当主链”。
2. **旧 AutoGPT / BabyAGI / MetaGPT 类模板**：demo 性质强，只有简单 loop，无 durable execution / event sourcing / compensation。缺少与 Temporal 的现成 bridge，容易 fake completion。
3. **纯 LangChain sequential chains (非 Graph)**：缺少 supervisor 层级控制环和 state machine 能力，无法支撑 L2 reconcile “期望态 vs 实际态” 的长期自运转。
4. **Argo Workflows / Flux Python client 作为主控**：k8s-centric，我们环境是 Windows local + Temporal，不匹配；会引入不必要的重型 infra 胶水。
5. **纯 verifier / self-refine / width 晋级 ladder 框架**（无真实 invoke harness）：违反“不要把手搓 policy/verifier 马拉松当推荐”。缺少 L3 真执行 + L5 真证据闭环，只能纸上谈兵。
6. **只有 Streamlit/Gradio demo UI 的 agent shell**：无 backend durable WF 绑定，无法实现“后台自己从材料池取意图 + 自修复”的自治要求。
7. **重型 CMS / 项目管理平台 (如 Plane / Taiga)**：违反 L0 “不要推荐重型 CMS/项目管理系统”，材料池只需要轻量 intake + manifest。

---

## 建议薄绑顺序（第 1 周只焊哪 2 个胶水）

**第 1 周优先焊**：
1. **L0 markitdown**（材料池 intake）—— 解决“怎么把用户给的材料/文本变成后台可读结构化 task_package”，是所有后续的入口。工作量小，立即见效。
2. **L3 OpenHands + GitPython**（执行平面 + commit 自动化）—— 解决“后台无自治、不能默认改仓→测→commit→自修复”的核心痛点。启用基本 MAPE-K 执行闭环。配合 L2 GitPython reconcile 观察即可形成最小自运转。

**第 2 周再焊**：
- L5 Langfuse (证据 trace + readback) —— 让验证/收尾有结构化证据可审计。
- L2 完整 reconcile 逻辑 + L1 Pydantic schema 对齐现有 manifest。
- L6 retry/critic 环 + L8 中文 readback。

这样第 1 周就能跑通“材料 → 执行 → commit → evidence”最小闭环，比继续手搓 verifier 稳得多。

---

## 开放问题（需用户/Grok 拍板）

1. **OpenHands Docker on Windows**：E:\XINAO_RESEARCH_WORKSPACES\S 和 D: 路径映射 + volume 权限 + 性能（WSL2 backend 还是 Hyper-V？）。是否接受 Docker 作为执行沙箱前提？
2. **OpenHands 使用范围**：只用其 sandbox execution env + CLI/API（推荐），还是允许其完整 agent loop？（后者可能与 LangGraph planner 重叠，需明确边界）。
3. **Langfuse**：self-host（需 Postgres/ClickHouse infra）还是 cloud？research evidence 敏感度如何？
4. **L0 task_package schema**：要与现有 `capabilities\manifest.json` / AAQ ledger 对齐到什么粒度？是否需要额外自定义 Pydantic models？
5. **MCP client**：指令中“FastMCP 等”具体指什么协议/实现？是 E2B MCP、Model Context Protocol 还是其他？是否需要额外 glue？
6. **优先级队列**：完全依赖 Temporal task queues/signals，还是在 L2/L3 增加 Redis + rq 作为外部 priority queue glue？
7. **L7 promotion gate**：策略晋升是人工 review + metadata，还是加 auto metric gate（需定义 metric 是什么）？L7 何时启动？
8. **Windows Py 3.12 实测**：OpenHands / SWE-agent / litellm 等依赖在目标环境下的实际兼容性（虽理论支持，建议小范围 smoke test）。
9. **证据 readback 目录结构**：是否统一用 `D:\XINAO_RESEARCH_RUNTIME\YYYYMM\evidence_<type>_<id>\` + ledger.jsonl 索引？还是保持现有习惯？
10. **用户面 cockpit**：中文 readback md 由 Grok 外脑直接展示，还是需要额外简单 file-watcher / web UI glue？

---

**调研结论**：以上推荐均为**成熟、 permissive license、高活跃度、Python 3.12/Windows 友好**的胶水仓库。每个都只改接缝（thin bind），不手搓核心逻辑，不替换 Temporal/LangGraph/LiteLLM。按建议顺序焊接后，可快速形成“材料池 → 计划 → durable 执行 → 证据 readback → 自修复环”的最小自治闭环，比继续安全模板马拉松稳健得多。

用户可直接把本文件转发给 Codex / Grok 继续讨论具体 implementation plan（第 2 阶段再 clone + 写薄 wrapper 代码）。

**END OF REPORT**
