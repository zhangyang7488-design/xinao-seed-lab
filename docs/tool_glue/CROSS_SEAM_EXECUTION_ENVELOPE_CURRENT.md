跨接缝执行封套与一致性协议｜当前有效

SENTINEL:XINAO_CROSS_SEAM_EXECUTION_ENVELOPE_PROTOCOL_V1
版本：v1.5
日期：2026-07-24
状态：CURRENT_ACTIVE

一、身份与边界

1. 本协议是《软件工具胶水宪法》明确纳入的唯一跨接缝窄域附录，只约束一次已选执行怎样穿过现有 adapter、Activity、worker、provider、fan-in 与 fallback 而不失真；宪法仍是唯一软件工程根权威。
2. 本协议不创造任务授权、continuous、provider 默认、调度、重试 owner、状态库、Gateway、policy engine、daemon 或第二控制面；领域目标与允许副作用只从当前用户请求和当前父对象取得，正式合同只能在其对象作用域与授权范围内细化约束和验收，不能创设、扩张或转移授权。历史合同不得借跨接缝传播成当前任务的准入门。
3. 只在设计、修改、调用或验收跨进程/跨 provider/跨 transport 接缝时按需读取，不加入每窗热上下文。
4. 本协议属于 S 工程载体的按需能力，不是 Codex 默认工作父对象或新澳原生研究前门。无明确其他任务时默认进入 `E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research`；只有当前请求明确是跨接缝工程事务，或 live 研究先暴露一个具名接缝缺口，才消费本协议。普通研究、长研究、科学、腿 A、continuous 或多个工人都不自动创建工程运行面。
5. 默认工人身份只引用主管—工人说明：普通 Grok WorkerPool 使用独立 Grok 额度并作为第一候选；Terra/Luna/Sol/Codex collaboration 共用 Codex 周额度，Codex collaboration 默认不调用。本协议只约束一个已经选中的接缝，不选择默认 provider 或把封套可用性变成派工门。

二、唯一执行封套

1. `LogicalExecutionContract` 在产生模型、网络、文件、数据库或其他真实副作用前，绑定同一 `work_key`、逻辑 operation、输入/上下文/规则/output contract 摘要、幂等身份、deadline owner，以及已选 provider/profile/model/capability/transport；合同自身以规范化摘要标识。
2. `ExecutionAttemptReceipt` 按实际 attempt 追加，记录 consumer、实际 executor/runtime、observed provider/profile/model/capability/transport/rules、终态、输出摘要与校验、artifact lineage，以及该 attempt 内全部 invocation 的 accepted/cancelled/failed token 分账。
3. provider 原生合同先判真伪，再由薄 adapter 生成公共 receipt；公共层不得把 provider 已拒绝、Cancelled、timeout、残文、错误 schema 或身份漂移翻译成成功。
4. 消费者登记表只发现真实入口、适配状态、validator 与证据；登记、容器健康、进程存在或 wrapper 返回零都不能自铸 `complete`。
5. 当一个真实消费者明确需要跨 transport 复用、typed dependency、隔离写域或重试谱系时，`WorkerPackageBatch` 才作为 provider/transport 中立的逻辑 DAG 与整包身份，绑定 parent work key、graph revision、package/work key、输入/context/rules/output contract、写域、依赖条件、result selector、consumer 和 acceptance。普通 Grok 研究/施工锥不因复杂、科学或多工人自动升级为 package；一旦真实选择 package，腿 A 与腿 B 才消费同一份 manifest 字节，不能各自产生同义 schema。
6. `WorkerDispatchEnvelope` 只绑定一次 leg/provider/profile/model/transport 选择、quota epoch、admitted package IDs 与上述 manifest ref/hash；transport、物理路径映射和额度快照不得反向进入 neutral package identity。
7. 尚未满足上游条件的逻辑节点保持 conditionally-ready；只有指定 `worker_terminal|owner_adopted|authority_applied|effect_verified` 条件到达并绑定精确 event/artifact pin 后才形成可执行 seal。`owner_verdict` 只是采用裁决，不能替代 adoption 或释放权威/effect 依赖；pin 变化生成同一 work key 的 `reseal_of` 后继和受影响依赖锥，不修改旧 seal 或新建第二 graph ledger。
8. 摘要域是版本化合同的一部分。当前公共记录身份只调用共享 `canonical_json_bytes` 的 `canonical-json-v1 + sha256`；文件、schema 与 manifest ref 绑定原始文件字节的 `raw-bytes-sha256-v1`，支持该字段的 manifest 必须显式携带 profile。producer、consumer 与 validator 不得各自解析后重排并偷偷重算；若要让不同 JSON 排版等价，只能新增 JCS/RFC 8785 profile、升合同版本、保留旧读新写与有界迁移，并用跨平台 golden vectors 验证。
9. `AuditAssessment` 只封印高价值审计的 assessor identity、assessment plan、四类冻结 pin、有界充分证据 ref/hash、实际 evidence-access 状态和 `CANDIDATE_FINDING`；它始终 `authority=false`、`completion_claim_allowed=false`、`repair_authorized=false`。`AuditAdjudication` 由 Codex Owner 绑定一个 assessment/finding、本地复现证据、bug-bar disposition、同族新证据与终态；`repair_authorized` 只能由公共 validator 推导，调用方不得自报。

三、跨接缝不变量

1. 执行现场必须用当前认证环境重新发现 profile/model/capability/rules/mount/version，但发现只验证既定选择；alias 不存在、能力不满足或 observed 不一致时在副作用前失败，不重新择模、不静默降级。
2. 若当前工程事务已经选择现有耐久执行面，实现可跨已选 transport 传播同一逻辑合同摘要。该链只拥有被选中的工程 execution，不是新澳研究父路线；task-run/events 是协调、声明与证据索引链，各执行组件只拥有自己产生的局部状态与调用证据；Git/PR、运行时 API 与领域 ledger 裁决物理事实。
3. 每次真实 provider invocation 都入账。父账必须等于全部子 invocation 的总和，并满足 `total = accepted + cancelled + failed`；不得只保留最后一次或把失败消耗抹掉。
4. 只有完成终态、selected 与 observed 一致、provider 原生证据有效、输出 schema/marker/内容尺通过、artifact/hash/lineage 绑定且 token 总账平衡，才可 accepted 并关闭本次 execution attempt/consumer boundary；accepted 不关闭逻辑 work unit、land/effect 谓词或父级完成。
5. cancelled、timed_out、failed、无 receipt、旧合同、规则漂移、晚到结果和证据篡改保持 unresolved；现有 reconciliation 修前置或生成同一合同的新 attempt，不能因局部失败结束主线。
6. Workflow replay 复用 history 中的既有结果；重新调用模型是新的 attempt/re-execution，不叫 replay。retry、timer、cancel、heartbeat、Continue-As-New 仍由 Temporal 统一拥有。
7. direct 与 WorkerPool 是腿 A 的有界生产 transport，不是降级代名词；只有现有 route receipt 或显式、事实化的新 route event 才能把某次调用定义为 fallback。结果必须回到同一 work-key、receipt 和 reconciliation，不能取得 owner 身份或形成第二循环。
8. worker outcome 必须引用同一 package manifest、dispatch envelope、公共 logical contract、真实 attempt receipt 与 hash-bound provider artifact；token 从 attempt receipt 自动导出，调用方不得自报 `accepted` 或 usage。
9. owner verdict 必须引用一个已验证 worker outcome，并绑定实际采用的 artifact；每个不可变 seal 只有一次明确 verdict。effect event 必须引用该 owner verdict，并由 `xinao.work_unit_finalizer_evidence.v1` 物理 readback 证明同一 artifact 已被真实 consumer 消费。投影永远非权威，只展示 outcome chain 是否闭合和 token conversion，不能铸造父级完成。
10. action-resume 的一次性 claim 是薄 outbox，不是“回调返回即成功”的锁文件。真实副作用 adapter 必须接收 expected version、side-effect identity 与 generation/fence，返回 typed CAS outcome 和物理 readback；claim 经 `claimed → aborted_pre_effect|effect_unknown|readback_verified → event_pending → closed` 收口，崩溃由显式 reconcile 恢复。Git/ref 使用原生 expected-old CAS，task-run/ledger 写入保持幂等；不新增数据库、daemon 或第二状态真源。
11. `parent_mainline_id`、`batch_id` 与 package `work_key` 是不同作用域，route/claim 不得借父级 key 代替 package 身份。`parent_mainline_id` 必须绑定当前父对象/task-run 的真实身份；父对象切换后不得回填历史 task-run。局部 `WAIT/NO_ACTION/transport failure` 只冻结受影响依赖锥；只有面向当前父目标的全局前沿 reconciliation 对精确 event prefix/hash、全部未闭对象、逐项排除理由与 wake proof 验真，才可把父级标为全局等待/无活，后续相关 event 自动使其 stale。
12. 同一 work key 跨窗恢复先消费最后一次成功且仍健康的 hash-bound route receipt 与当前 carrier；继续执行不能从架构文字重新选 transport。只有需求、健康或净收益事实变化时，才写显式新 route event 并迁移；一条新路径的 pre-provider 失败只隔离该路径，不证明 provider 或父主线不可用。
13. 同合同、同语义输入且已有 accepted ancestor 时，当前 carrier 可产 `ACCEPTED_IDENTICAL_REUSE`，但必须在 provider 前验证 ancestor 的合同、manifest、attempt、selected=observed 与产物哈希。当前 attempt 的五项 usage 全为零，历史消耗只进入 `subject_attempt_usage`；复用不改写旧 attempt，不冒充新的模型调用或父级完成。
14. `high_value_audit` package 必须 candidate-only、无权威写域并输出公共 `AuditAssessment` schema；provider 的优先级只是可替换路由事实，真正准入条件是独立访问有界充分证据包的能力与事后 hash 证明。`audit_repair` package 必须把 assessment、Owner adjudication 与同族 prior adjudications 作为 hash-bound input；公共 gate 复核同 work key、冻结 pin、Owner 复现、bug bar 和新证据后才可执行。缺任一条件 fail closed 为候选或终态，不创建下一 repair。

四、外部成熟完整性

1. 未知或发生事故的接缝，先把本机真实实现与当前官方规范、官方 SDK/reference 和可信成熟 integration 放入同一选区；吸收 capability negotiation、typed schema、幂等、deadline/cancel、trace、observed identity 等稳定语义，并让对照实际改变最薄实现。
2. 外部成熟完整性不是产品名词清单。MCP、CloudEvents、OpenTelemetry 或其他实现只在当前接缝净收益为正时通过 adapter 映射；易变字段名、具体产品和未采用方案不进入本协议真源。
3. OPA、Sigstore、Merkle、SPIFFE、TUF、SLSA、Kubernetes admission、人工审批链等只在明确威胁模型和成熟准入后另行采用；不得作为单人本机生产力的默认前置。

五、机器生效面

以下入口全部位于 S 工程能力面。它们继续作为可复用工程实现存在，但不被新澳原生研究默认加载；一个 live 具名消费者选择本协议后才进入其依赖锥。代码或测试存在不证明已移除的平台仍是 current，也不证明研究必须等待这些入口 ready。

1. 逻辑合同与 receipt 纯函数：`services/agent_runtime/execution_contract.py`。
2. Grok provider adapter：`services/agent_runtime/grok_execution_contract_adapter.py`；`xinao.grok.shared_execution_contract.v1` 保持 provider 真源，不被公共层替代。
3. JSON Schema：`services/agent_runtime/schemas/execution_logical_contract.v1.schema.json` 与 `execution_attempt_receipt.v1.schema.json`。
4. 当前消费者登记：`services/agent_runtime/execution_consumers.v1.json`；只有共同 conformance、旧 history replay 与 fresh 真实 canary 均有耐久证据，消费者才可标 `complete`。
5. 公共回归：`tests/test_cross_seam_execution_conformance.py`；provider、fan-in、promotion 与恢复负测继续留在各自现有测试，不复制第二套评测平台。
6. 动态整包、dispatch envelope、outcome 投影与 token conversion：`services/agent_runtime/dispatch_economics.py`；构造、校验、投影和正负回归只调用该公共实现。
7. compact/换窗恢复与权威副作用前置：`services/agent_runtime/action_resume_receipt.py`；context slice 由 `services/agent_runtime/context_slice_manifest.py` 提供。checkpoint 与 reuse index 只是 task-run/events 的可重建指针。
8. 横向问题与工作面生命周期的唯一语义定义只引用《软件工具胶水宪法》同名章节；对应机器入口为 `services/agent_runtime/system_awareness_consumer.py`，typed task-run 写入适配器为 `scripts/record_problem_transition.py`，真实消费者状态登记在 `services/agent_runtime/execution_consumers.v1.json`。本附录只绑定实现入口，不复制其生命周期、原子写入或 fail-closed 正定义。
9. 无窗口 task-run/outcome fan-in：`scripts/record_dispatch_outcome.py` 与 `services/agent_runtime/integrated_bus_runner.py`；后台 Python 必须经显式解释器和 Windows no-window flag 启动，不改变全局文件关联。
10. 高价值审计与 Owner 裁决纯函数：`services/agent_runtime/audit_adjudication.py`；候选输出、宿主 assessment 与 Owner adjudication 的 JSON Schema 分别为 `audit_candidate_findings.v1.schema.json`、`audit_assessment.v1.schema.json` 与 `audit_adjudication.v1.schema.json`。宿主嵌入认知审计和直接工具独立 V 的能力路由由 `services/agent_runtime/supervisor_worker_selector.py`、`routing_policy_reader.py` 与当前参数真源消费；`services/agent_runtime/dispatch_economics.py` 和 `scripts/build_worker_package_batch.py` 对 audit/repair package 执行强制门。OpenAI-compatible 认知工人的固定入口继续使用现有 `C:\Users\xx363\CodexLaunchers\Invoke-Codex-OpenAiRelayWorker.ps1`，其 `cognitive_audit` 模式只接收哈希绑定的 context manifest 与候选输出 schema；每次调用还必须绑定 provider contract 路径与预期 hash，具体 API 的 Base URL、模型/别名、KeyPath 句柄、健康/429 语义、证据入口和恢复说明只保存在其可选薄适配器封套中。存在的适配器必须有足够自恢复元数据且不得含密钥值；整对适配器可增删替换，只改变当前可选绑定，不改变固定入口、候选权限、审计语义或 Owner 权限。

六、变更与完成尺

1. 新消费者先登记真实状态，再薄适配原生合同；没有实现和证据时标 `adapting/partial/legacy`，不得用文本承诺补绿。
2. 合同字段或语义变化必须新版本；Temporal 调度顺序、参数或决策语义变化使用新的 patch/workflow version，旧 patch 不改义，并先过 retained-history replay。
3. 完成必须同时具备：机器 schema、公共与 provider 双层验证、消费者登记、正负 conformance、全账、fresh-process 真实任务 canary、旧 history replay、D 盘 hash 证据和独立回滚。

本协议只消除跨接缝失真；它不复制宪法、领域合同或运行时，也不把技术规格负担退回用户。
