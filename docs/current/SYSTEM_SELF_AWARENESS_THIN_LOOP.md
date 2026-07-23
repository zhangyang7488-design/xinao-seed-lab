# 横向系统自觉薄闭环

定位与关系：本文件是 S 工程内的消费者/复现补充，不是新的合同、状态真源或控制面。稳定主线入口决定何时发现它；当前工具胶水宪法仍定义软件角色、默认主路、授权和完成尺；`新澳双腿执行结构树_腿A直调_腿B后台_当前有效.txt` 只投影腿 A/腿 B 的机器拓扑。本文件只说明同一个逻辑 work unit 如何穿过这些载体。发生冲突时本文件让位于前述上位文本。

状态：仓库工作单元/临时载体这一切片已接入 record producer、只读 scanner、pre-action guard 和 S 热入口；更宽的 completion、成本、问题、身份、Temporal 与恢复面仍按各自 `verified|partial` 证据报告，不因本切片通过而一并冒充闭合。task-run events 是父级协调、声明与证据索引链；腿 B 的 Temporal history 是耐久执行 owner；Git/PR/运行时 API/领域 ledger 是物理事实。本文件、checkpoint、records、投影和 receipt 都不授予 parent completion 或删除权。

## 父级结果

目标不是把归档施工包逐项做完，也不是建设 ITSM 平台。目标是减少用户亲自撞墙后才发现横向能力只有 1–3 的负担：主动用成熟体系校准与未来主线有关的维度，把整体拉到可消费的 5–6；新问题进入同一条发现、归族、局部/系统判断、修复选择、效果验证、复发升级链。

归档包只是候选地图和回归素材。它遗漏父级结果时补，出现第二真源、报告绿、无消费者 schema 或成熟度 9 式过建时拒绝。

## 一条链，三个消费者

```text
existing task-run events / ledgers / runtime APIs / evidence
               |                         |
               v                         v
 system_awareness_task_run_scanner   action_resume_preaction_guard
  - problem family                   - replay event tail
  - token -> outcome                 - bind typed live facts
  - typed work-unit projection       - same-work-key pause/resume fence
  - prior projection recovery        - durable one-effect claim
               |                         |
               +------ non-authoritative receipts ------+
                                      |
                                      v
                   existing dispatch/apply/land/promote decisions

 worktree_lifecycle_scanner（同一链上的物理载体投影）
  - Git porcelain、HEAD/base、tracked/untracked/ignored 对账
  - active/paused/archive/retire candidate/retired tombstone
  - 永远不 remove/prune/unlock/move，不授予 delete 或 completion

 publish-worktree-record（现有 task-run 事件后的生产端）
  - 固化 work_key/carrier/generation/observation/event-prefix
  - 输出 hash-bound records 及下一条 records-published event 所需引用
  - 只写非权威记录，不执行 Git mutation 或删除
```

没有新增问题数据库、事件总线、Router、scheduler、daemon、GitHub Issues 权威队列或 parent completion owner。

## Work unit 与临时载体生命周期

三种身份不可混用：

- `work_key`：用户意图下的逻辑工作单元；从腿 A/腿 B、窗口、commit、PR 到真实效果保持不变。
- branch/worktree/D artifact 只是该 work key 的临时 carrier：换窗优先续用仍适配的绑定载体，不按窗口增殖半成品；Git 解析根不自动取得写入身份，carrier 闭合后必须 land、freeze/archive 或 retire。
- `carrier_id + carrier_generation`：某一次 worktree/线程/Temporal run 等临时载体实例；同路径重建必须是新 generation。
- `side_effect_id`：一次 dispatch/apply/land/retire 或状态转换；不能拿路径哈希代替，也不能跨动作复用。

生命周期不是第二状态机，而是对现有事件和物理事实的薄投影：

```text
planned -> active -> verifying -> land_requested -> landed -> effect_verified
              |                                             |
              +-> paused/interrupted -> live reconcile -----+
                                                            |
temporary carrier: active/paused -> archive review or retire candidate -> retired tombstone
```

规则：

1. 用户切换任务或窗口中断时，原 work unit 进入 paused/interrupted；不暗中新增 owner、daemon 或第二 turn。pause 只冻结同一 work key；新窗口从 task-run event tail 找到最新 hash-bound records，重算 Git/PR/运行时事实，并以同 key 的 `work_unit_resume_reconciled` 哈希证据解冻。无关 action/result 不能解冻它。
2. `landed` 需要当前目标分支/PR/检查/merge 的物理 readback；`effect_verified` 需要任务要求的真实消费者或运行时窗口。commit、push、PR green、报告 PASS 彼此不能代替。
3. worktree records 必须把逻辑 `work_key`、载体 generation、当前 observation、事件前缀和单次 side effect 绑在一起；旧事件不能给同路径重建或后来漂移的载体复用。
4. ignored 内容默认是未分类物料。dirty、ignored、未吸收提交、锁定、prunable、primary/base、事实漂移或 finalizer 缺失都不能成为 retire candidate。
5. archive 只有隔离恢复和内容对账的 hash-bound receipt 才能标为 preserved；即便如此也只进入 owner review，绝不自动清除 removal finalizer。
6. 父级全局等待只接受 `xinao.global_frontier_reconciliation.v3`：每个外部阻塞必须拆成独立 atom，同时绑定当前事件头下的外部观察与“现授权对象/拓扑内确实不能建设”的结构化反事实。只要存在本机可建设 atom，父级保持 open；checkpoint、next_frontier、提示词、模型输出、报告、旧 reconciliation receipt 与 v1/v2 receipt 都不能证明外部性。
7. `retire_candidate` 只是“当前 owner 可重新核验的移除候选”，不是 `retired`。真实移除后还要同时读取 Git inventory 与字面路径证明缺席并写 task-run result；重算 path ID 且带 event-prefix 的 tombstone 才把成功退役与意外目录消失区分开。
8. 所有投影固定 `authority=false`、`delete_authority=false`、`automatic_delete_allowed=false`、`completion_claim_allowed=false`。

## 问题闭环

1. 发现：从既有失败事件、reason code、真实运行时差异和消费者失败生成候选；单纯目录、报告或 PASS 不算问题关闭。
2. 归族：`family_signature + governing_cause` 合并同根因事件，保留每个 `event_id/work_key`；证据显示不同 governing cause 时 split，历史引用不删除。
3. 判断：单 work key/单组件默认 `local_defect`；跨 work key、跨组件、缺消费者、控制边界或 governing assumption 默认 `systemic_capability_gap`。
4. 选择：输出 `small_repair | structural_repair | no_build`。与父目标无关或预期净收益明确非正时可 `no_build`，不为维持运行制造工程。
5. 关闭：必须同时有真实消费者或 live canary，以及类型明确为 monitoring/effectiveness/observation 的已完成效果窗口；同一条 real-consumer 证据即使自称 `window_completed` 也不能双算。diff、单测、Promptfoo 单独为绿时只能 monitoring/partial。
6. 写入隔离：全量 `scan_task_run` 对 dispatch、frontier、usage、carrier 与问题投影继续整体 fail-closed；问题写入适配器只调用同一 task/state/events 真源上的严格 problem projection，仍完整校验 typed transition 的哈希、事件绑定与代际。查重、代际推导和预验证只消费同一个不可变快照；候选转移在产物发布前完成生命周期预验证，再以 `expected-events-count + expected-events-sha256` 进入 canonical task-run 文件锁。头部漂移必须拒绝/重算，完全相同事件只作幂等重放，不能写入重复或跳代。
7. 复发：effective 后出现新的同根因事件即 reopen，保留旧证据并提升修复层级候选。

## 默认授权记录

用户已明确授权这条链在不违反上位合同和当前对象边界时，默认执行完成结果所需的原生能力链；后续窗口可从仍在进行的同一 task-run 与其授权收据恢复已给出的任务范围，不应为下列普通、可回滚动作重复索权。本文件本身不创造、延长或扩大授权：

- 读取现有事实、做当前官方/成熟工程对照、问题归族和局部/系统判断；
- 在本任务隔离 worktree、D 证据目录和专用 task-run 内修改、测试、生成 receipt、运行 fresh-process canary；
- 使用现有 Grok 工人总线做候选研究/复现/critic，Codex 保持唯一正式写者与终验；
- 做 Temporal/Postgres/文件/进程的只读对账，以及在既有消费者内拒绝 stale、duplicate、身份漂移或错误完成权；
- 在同一对象和既有拓扑内实施最小可回滚修复、回归、效果验证与复发升级。

若同一仍在进行的任务已经把具名仓库的 push/PR/merge 写入当前任务范围，就沿用该范围而不重复询问；否则新发布目标、跨仓 push、账户/付款/秘密、删除未分类或重要对象、新增常驻控制面、改变 live Temporal 路由、live 数据库/容器/volume/restore mutation、接管或中断另一 TUI/run/worktree/mainline，仍需当前任务授权。授权不跨任务、对象或效果位阶传递。

稳定链路范围投影见 `D:\XINAO_RESEARCH_RUNTIME\evidence\system_self_awareness_closure\20260720\authorization_scope.v1.json`；每次实际外部效果仍以当前 task-run 的 `task.json.scope.external_effects` 为准。本次具名仓库发布范围记录在 `worktree-lifecycle-closure-20260720` task-run 中。

## 成熟外部模式如何被本地化

- Google SRE：事故行动项必须有 owner、跟踪身份和可测终态；重复事故要追问是否只是 Band-Aid。本地只取 problem family、effectiveness 和 recurrence escalation，不复制组织级工单系统。
- Kubernetes controller：desired/current reconciliation 与 condition/status 分离。本地只做按需只读 reconciliation，不新增常驻 controller。
- OpenTelemetry：用传播身份关联事件。本地复用 `event_id/work_key/side_effect_id/evidence_ref`，不建第二日志后端。
- SLSA provenance：声明身份必须和观察到的执行/产物身份绑定。本地采用 declared-selected-observed、repo pin-live build 和哈希收据。
- Temporal Worker Versioning：Deployment name + Build ID 才标识版本，队列/poller 也是运行闭合的一部分。本地只读 describe；发现 drift 时 partial，不自动改 current version。
- PostgreSQL PITR：WAL 归档存在只是恢复材料；必须实际 restore 并检查目标数据。本地 live 只读探针保持 partial，未经新授权不动容器或 volume。
- Git worktree：用稳定 porcelain 盘点，locked/prunable/missing 是不同物理状态；remove/prune 是 owner 动作而非扫描副作用。本地只取可重放盘点与移除后 readback，不把多 worktree 变成多主线。
- GitHub merge queue/auto-merge：required checks 与最新 base 决定何时可合；PR green 仍不等于运行时效果。本地 land finalizer 记录 commit/remote/PR/merge 事实，effect finalizer 单独关闭。
- Temporal Workflow ID/Continue-As-New：业务身份跨 run 保持，run ID 是执行实例；cancel 是协作式的，Activity 外部副作用仍需幂等键。本地对应 `work_key`、carrier identity 与 `side_effect_id` 三轴。
- Kubernetes finalizer/owner reference：desired state、observed status 与删除前置分开；对象消失不自动证明清理成功。本地用 retire candidate + task-run tombstone，不引入常驻 controller。
- DORA 小批量/主干开发：短命分支、频繁合入、少量活跃分支降低交付风险。本地把 worktree 当短期 carrier，完成后 land 或明确 archive/review，不让“可能有用”永久占据活跃施工面。
- OpenTelemetry context propagation：跨进程传播 correlation，不把 trace 当业务真相。本地让同一 `work_key` 穿过腿 A/腿 B，保留 event/side-effect/PR/SHA pins，但完成仍由现有事实消费者裁决。

完整对照收据：`D:\XINAO_RESEARCH_RUNTIME\evidence\system_self_awareness_closure\20260720\mature_pattern_crosswalk.v1.json`。

## 入口

```powershell
python scripts/run_system_awareness_consumer.py scan-task-run --task-run-dir <run> --output <receipt>
python scripts/run_system_awareness_consumer.py scan-worktrees --repo-root <repo> --base-ref origin/main --task-run-dir <run> --output <receipt>
python scripts/run_system_awareness_consumer.py publish-worktree-record --repo-root <repo> --records <records.json> --worktree <path> --task-run-event-ref <events.jsonl#event-id> --carrier-id <id> --carrier-generation <n> --purpose <text> --owner <owner> --declared-state active --work-key <key> --side-effect-id <id>
python scripts/run_system_awareness_consumer.py temporal --repo-manifest <pin.json> --live-snapshot <describe.json> --output <receipt>
python scripts/run_system_awareness_consumer.py recovery --input <probe.json> --output <receipt>
python scripts/record_problem_transition.py record --task-run-cli <task_run.py> --task-run-root <root> --task-run-id <run> --transition-type problem_observed --family-signature <family> --governing-cause <cause> --work-key <key> --component-id <consumer>
python scripts/run_action_resume_consumer.py issue ... --output <receipt>
python scripts/run_action_resume_consumer.py consume-canary ...
```

`scan-task-run` 只从 hash-bound task-run 事实链重放 problem_ref、效果与关闭状态；`--previous-problems`、`--effectiveness-evidence` 或 `--close-requested` 等外部注入会以 `EXTERNAL_PROBLEM_FACTS_NOT_AUTHORIZED` 拒绝。写入只能经 `record_problem_transition.py` 形成 typed transition 并原子追加。`scan-worktrees` 优先从 task-run event tail 反向发现最新 hash-bound records，也可显式传 `--records`；没有 records 时全部 fail closed 为 unclassified。

任何写动作先核对 event head、world、已存在的 typed work key、精确 `next_action/action_digest` 和 side-effect identity，取得由 `run_id + work_key + side_effect_id` 固定寻址的 one-shot claim 后再立即复验一次；apply 必须绑定可重读 live fact，land 必须绑定同 key 的 Git remote/PR readback，retire 必须绑定同 key 的 carrier inventory，自称 `work_pin` 或无关文件不能过门。effect 后、event 前崩溃会留下 uncertain claim 并拒绝重放，必须先读回真实效果；消费记录也不能代替动作后的 task-run result 与物理 readback。

## 当前明确未冒充闭合的项

- `xinao-dualbrain-promoted` repo pin 与 live current build 漂移；两个关联 task queue 当前均为 UNVERSIONED 且无 poller：`partial`，未改 live 路由。
- `shiwu-ku` WAL 正在归档，但未做隔离 restore + 下游 canary，且 data checksums 为 off：`partial`，备份目录存在不等于恢复 verified。
- BR-DOMAIN-001..004 仍 dependency-gated；没有真实领域 consumer 前不造空壳。
- 可唤醒 wait 已接入只读 v3 父级消费者与硬负例；它只裁决现有 wait 候选，不创建 durable wait 控制面，也不取得父级 owner 权。
- Foundation 腿 B 的 operation/owner-generation/workflow-run 到 task-run work key 仍缺只读 seam adapter；本包不修改正在施工的 Foundation 写域，先按相邻问题记账而不伪称已汇流。
- token 守恒只有出现独立 `native_usage_total_observed` 证据才可报 balanced；Promptfoo evaluation verdict 与 provider invocation status 已分轴。没有独立总账时为 unknown。

这些 open/partial 是这条系统自觉链发现并诚实记账的结果，不是本隔离包的假失败，也不能被报告绿覆盖。
