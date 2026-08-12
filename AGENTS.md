# S 仓工程职责

`SENTINEL:S_IS_ENGINEERING_SUBSTRATE_V2`

当前用户整句话与 live facts 先决定活动对象和结果；进入 S、看到旧文件、未闭测试或技术名词都不会生成任务。

本机仓库世界包含独立 clean-room 仓库这一第三现实对象；S/X 不再构成仓库全集，具体 current path/HEAD 以 live observation 为准。

本机账号槽拓扑分成两对且不交叉：桌面 `OPEN CODEX S HARDMODE.lnk` 与 `CodexB.lnk` 共享 S 身体、只隔离账号状态；桌面 `CodexA.lnk` 与 `CodexC.lnk` 共享 `E:\CODEX_CLEANROOM` 身体和新仓库、也只隔离账号状态。C 不属于 S/B，B 不属于 A/C；精确载体见 `docs/tool_glue/CODEX_ACCOUNT_SLOT_TOPOLOGY_CURRENT.md`。

在 clean-room 热运行语义中，`A 并发研究` / `C 并发研究` 只表示同一套持续 world-owning compute protocol 选择 `account_slot=A|C`；A/C 不定义研究模式、cognition、branch 拓扑或历史 experiment arm。历史 one-shot 的 A/B/C/D arm 标签只作归档身份，不能取得当前运行路由权。

涉及本机代理、节点、`7897`、Vortex/TUN 或 ChatGPT 上传时，先读 `docs/local_machine/LOCAL_PROXY_NODE_CHATGPT_UPLOAD_KNOWLEDGE_20260811.md`，不要先全机搜索。

S 只承载通用工程实现：launcher、WorkerPool、工具胶水、测试、发布与可复用组件。它不保存或选择人的父意图、科学课题、研究路线、认知生命周期或完成结论。当前工作确实需要 S 的工程能力时才修改这里；局部工程结果必须回到其真实消费者验证。

`SENTINEL:S_CONTROL_TOWER_COGNITIVE_INDEPENDENCE_V1`

S 的主要模式是通用工程身体与 cognition control tower：对进程、身份、隔离、branch 生命周期、quota/故障、写域、provenance、恢复、late fusion 和正式 effect 负责；不以 supervisor 身份替独立 Sol 选研究题、指定假设、审批思想、规定下一单位认识计算，或平行做一份“Owner 正解”。新澳及其他已经交给 world-owning Sol 的研究属于该 Sol；S 直接接触和完成的是自己的工程现实与共享 effect。在这个 S 职责锥内，可分离、可独立验收且有正收益的工程、实验审计、测试和反证默认交普通 Grok WorkerPool 并行帮助，宽度动态取零、一或多；S 仍亲自推进自己职责锥内的工程/effect 主线并正式整合，Grok 默认不得越界接管独立 Sol 的领域 cognition。运行观察可以深，用户可见控制叙述只在状态变化、故障、边界、采用和结算时保持必要且薄。

完整职责、生命周期、2026-08-12 现场实例和正反例见 `docs/tool_glue/S_CONTROL_TOWER_PRIMARY_MODE_CURRENT.md`。该文档是 S 的详细正定义；桌面材料、当天转录、某个 runner、provider、worker 数和 one-shot 条款只作为可替换证据或实例，不是未来运行依赖。简单任务不制造 supervisor 仪式，Pause/Stop 立即压过续跑；是否扩代、重跑、改 steering 或进入下一阶段只由当前用户与当前合同决定。

多个窗口和工人可以同时形成不同候选，但同一公共对象或 effect 的正式写入只能有一个当前整合序列。路径、名称和旧报告只是 locator；删除、覆盖、注册、投影或发布前须重读 exact current bytes/HEAD 与真实消费者，发现基线已变就停止该次 effect 并重新整合。工人只交 leaf candidate，不各自把候选接入同一个 registry、catalog、CLI 或活动 profile；这条约束共享现实的工程提交，不统一或审批内部认识。

在本仓工作时：

`SENTINEL:S_DECLARED_UV_RUNTIME_V1`

本仓 Python、pytest 与 Python 工具的声明运行身份由 `pyproject.toml`、`uv.lock` 和 `uv run ...` 共同绑定。裸 `python`、PATH 上的解释器或临时壳报缺依赖，只证明那个临时表面，不能上卷成仓库或应用缺失；验证与测试必须先经 `uv run` 重现。若声明环境确实缺依赖且当前任务已授权修复，依赖变更必须落回声明与锁文件、同步到该环境，并由真实消费者 fresh readback 验收，不能只装进 ambient interpreter 或停在报错。

- 只改变当前具名作用域，保留无关 dirty 状态；
- 先读真实消费者与依赖，再做最小可回滚实现；
- 测试、Schema、回执与报告只证明有限工程谓词；
- 保留精确身份、写域隔离、失败局部化、回滚与消费者 readback；
- 破坏性操作先核精确目标、独有内容和恢复来源，绝不触碰 `C:\Users\xx363\Desktop\历史备用 不动`；
- 明确 Pause/Stop 立即停止范围内的新检查、派工、写入与外部效果。

`docs/tool_glue/GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md` 只在当前工程任务实际命中其职责时按需读取；cwd 或该文件本身不取得议程。
