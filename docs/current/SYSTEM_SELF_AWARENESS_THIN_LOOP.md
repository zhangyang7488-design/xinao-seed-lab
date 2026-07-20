# 横向系统自觉薄闭环

状态：本文件描述隔离分支上的消费者边界与使用方式；task-run events、运行时 API、领域 ledger 和既有证据仍是事实真源。本文件、checkpoint、投影和 receipt 都不授予 parent completion。

## 父级结果

目标不是把归档施工包逐项做完，也不是建设 ITSM 平台。目标是减少用户亲自撞墙后才发现横向能力只有 1–3 的负担：主动用成熟体系校准与未来主线有关的维度，把整体拉到可消费的 5–6；新问题进入同一条发现、归族、局部/系统判断、修复选择、效果验证、复发升级链。

归档包只是候选地图和回归素材。它遗漏父级结果时补，出现第二真源、报告绿、无消费者 schema 或成熟度 9 式过建时拒绝。

## 一条链，两个消费者

```text
existing task-run events / ledgers / runtime APIs / evidence
               |                         |
               v                         v
 system_awareness_task_run_scanner   action_resume_preaction_guard
  - completion boundary              - replay event tail
  - token -> outcome                 - bind world/work pin
  - problem family                   - stale/duplicate/stop fence
  - identity/runtime truth           - atomic one-shot consume
               |                         |
               +------ non-authoritative receipts ------+
                                      |
                                      v
                   existing dispatch/apply/land/promote decisions
```

没有新增问题数据库、事件总线、Router、scheduler、daemon、GitHub Issues 权威队列或 parent completion owner。

## 问题闭环

1. 发现：从既有失败事件、reason code、真实运行时差异和消费者失败生成候选；单纯目录、报告或 PASS 不算问题关闭。
2. 归族：`family_signature + governing_cause` 合并同根因事件，保留每个 `event_id/work_key`；证据显示不同 governing cause 时 split，历史引用不删除。
3. 判断：单 work key/单组件默认 `local_defect`；跨 work key、跨组件、缺消费者、控制边界或 governing assumption 默认 `systemic_capability_gap`。
4. 选择：输出 `small_repair | structural_repair | no_build`。与父目标无关或预期净收益明确非正时可 `no_build`，不为维持运行制造工程。
5. 关闭：必须同时有真实消费者或 live canary，以及类型明确为 monitoring/effectiveness/observation 的已完成效果窗口；同一条 real-consumer 证据即使自称 `window_completed` 也不能双算。diff、单测、Promptfoo 单独为绿时只能 monitoring/partial。
6. 复发：effective 后出现新的同根因事件即 reopen，保留旧证据并提升修复层级候选。

## 默认授权记录

用户已明确授权这条链在不违反上位合同和当前对象边界时，默认执行完成结果所需的原生能力链；未来窗口恢复的是这项既有任务授权，不应为下列普通、可回滚动作重复索权：

- 读取现有事实、做当前官方/成熟工程对照、问题归族和局部/系统判断；
- 在本任务隔离 worktree、D 证据目录和专用 task-run 内修改、测试、生成 receipt、运行 fresh-process canary；
- 使用现有 Grok 工人总线做候选研究/复现/critic，Codex 保持唯一正式写者与终验；
- 做 Temporal/Postgres/文件/进程的只读对账，以及在既有消费者内拒绝 stale、duplicate、身份漂移或错误完成权；
- 在同一对象和既有拓扑内实施最小可回滚修复、回归、效果验证与复发升级。

仍需新的当前授权：发布/push、账户/付款/秘密、删除未分类或重要对象、新增常驻控制面、改变 live Temporal 路由、live 数据库/容器/volume/restore mutation、接管或中断另一 TUI/run/worktree/mainline。授权不跨对象位阶传递。

机器记录见 `D:\XINAO_RESEARCH_RUNTIME\evidence\system_self_awareness_closure\20260720\authorization_scope.v1.json`。

## 成熟外部模式如何被本地化

- Google SRE：事故行动项必须有 owner、跟踪身份和可测终态；重复事故要追问是否只是 Band-Aid。本地只取 problem family、effectiveness 和 recurrence escalation，不复制组织级工单系统。
- Kubernetes controller：desired/current reconciliation 与 condition/status 分离。本地只做按需只读 reconciliation，不新增常驻 controller。
- OpenTelemetry：用传播身份关联事件。本地复用 `event_id/work_key/side_effect_id/evidence_ref`，不建第二日志后端。
- SLSA provenance：声明身份必须和观察到的执行/产物身份绑定。本地采用 declared-selected-observed、repo pin-live build 和哈希收据。
- Temporal Worker Versioning：Deployment name + Build ID 才标识版本，队列/poller 也是运行闭合的一部分。本地只读 describe；发现 drift 时 partial，不自动改 current version。
- PostgreSQL PITR：WAL 归档存在只是恢复材料；必须实际 restore 并检查目标数据。本地 live 只读探针保持 partial，未经新授权不动容器或 volume。

完整对照收据：`D:\XINAO_RESEARCH_RUNTIME\evidence\system_self_awareness_closure\20260720\mature_pattern_crosswalk.v1.json`。

## 入口

```powershell
python scripts/run_system_awareness_consumer.py scan-task-run --task-run-dir <run> --output <receipt>
python scripts/run_system_awareness_consumer.py temporal --repo-manifest <pin.json> --live-snapshot <describe.json> --output <receipt>
python scripts/run_system_awareness_consumer.py recovery --input <probe.json> --output <receipt>
python scripts/run_action_resume_consumer.py issue ... --output <receipt>
python scripts/run_action_resume_consumer.py consume-canary ...
```

`scan-task-run` 可用 `--previous-problems` 保留 problem_ref 与历史，用 `--effectiveness-evidence --close-requested` 做关闭/复发判断。任何写动作先核对 event head、world、work key 和 side-effect identity，取得 one-shot claim 后再立即复验一次；复验失败会把 claim 固化为 rejected，消费者不会运行。

## 当前明确未冒充闭合的项

- `xinao-dualbrain-promoted` repo pin 与 live current build 漂移；两个关联 task queue 当前均为 UNVERSIONED 且无 poller：`partial`，未改 live 路由。
- `shiwu-ku` WAL 正在归档，但未做隔离 restore + 下游 canary，且 data checksums 为 off：`partial`，备份目录存在不等于恢复 verified。
- BR-DOMAIN-001..004 仍 dependency-gated；没有真实领域 consumer 前不造空壳。
- 可唤醒 wait 只有谓词与负例；本任务按用户要求完成后停止，不创建 durable wait 控制面。

这些 open/partial 是这条系统自觉链发现并诚实记账的结果，不是本隔离包的假失败，也不能被报告绿覆盖。
