# Codex 薄情境上下文生产合同

`SENTINEL:THIN_SITUATION_CONTEXT_PRODUCTION_V1`

当前接入由薄情境观察、`CurrentSituation` checkpoint 与 S/B `Context Fabric` 组成。它们都只提供受限、可失败的证据；不创建持续主体、任务、路线、Owner、授权、Stop 或完成状态。Fabric completion 合同见 `S_CONTEXT_FABRIC_CURRENT.md`。

## 当前消费者与兼容期

- `UserPromptSubmit` 通过 `scripts/codex_situation_context_hook.py` 先保留 `HUMAN_WORDS_BEFORE_ARTIFACTS_V2`，然后由 Fabric hook 捕获当前 prompt 但在本次 readback 中排除它；加入有 source refs 的 bounded historical materialization，最后附机械 `RuntimeObservation`。观察只描述 hook child、cwd、Git 和活动规则文件；自报字段仍分开标记，未观测的权限/工具面保持 `UNKNOWN`。
- `SessionStart` 由同一 Fabric hook 捕获、记录 session-lineage node，并在 `resume|compact` 时尝试加入 bounded Fabric view。只有 Fabric 无法形成该视图时，才回退读取当前 exact `session_id` 下已经显式写入的 provisional `CurrentSituation`；不会双重注入两个 current view。任一可选表面忙、损坏、过大或不满足策略时均省略并继续。
- `Stop` 捕获 surfaced assistant message，并只对当前闭合 round 运行有界 structural producer；`PreCompact` 仅捕获边界；`PostCompact` 与 `SessionEnd` 捕获边界后只运行该边界的 structural segment/current-seed producer。完整历史 replay 只能由显式 manager/recovery 操作执行，不能进入 3–5 秒 hook 热路径。没有 hook 会自动写 CurrentSituation、推断语义纠偏、恢复 task frontier、续跑旧工作，或让 lineage node 授权 continuation。

兼容期内，热消费者走 `render_hook_context()`/`render_materialized_context()`；公共 `rehydrate_context()` 是独立、mount-checked、持久化 materialization API，返回 `continuation_authorized=false`，不是当前 hook 的第二条自动续跑通道。

S/B 两个账号载体共享 S 源码、`hooks.json` 与 `config.toml`；仅账户凭证、session 和产品强制绑定的账户状态分槽。未知 `CODEX_HOME`、`E:\CODEX_CLEANROOM` cwd、CodexA/C、新仓库 Sol 和研究 session 都不得 mount 或继承 S/B Fabric 历史。

## CurrentSituation 的独立边界

`scripts/manage_current_situation.py` 是唯一显式写入口。`NO_MATERIAL_CHANGE` 不落盘；`MATERIAL_REVISION` 以 generation/projection-hash CAS 替换 current，并把 before/after 与 transition 写入冷 revision receipt；明确结束、换对象或被替代时 `retire` 写 tombstone 与冷回执。超过七天的 checkpoint 不再热注入。

CurrentSituation 始终 `provisional=true`、`authority=false`，并且不是 Fabric event/projection 的 canonical source。Fabric 事件、structural projection、correction、lineage 与 materialization 同样是 `authority=false`、`instruction_source=false` 的证据读取。Fabric 成功时它是唯一历史 materialization；CurrentSituation 只作迁移/故障 fallback。两者都不能互相升级、从文件/历史/模型输出自动写入，或压过当前整句话和 live facts。

## 安全与恢复边界

- checkpoint 是会被模型看见的本地明文上下文，禁止 token、密码、API key、cookie 等秘密；会话 ID 只接受规范小写 UUID，session/current 文件和目录拒绝 link/redirect。
- Fabric 对 secret-like surfaced text 只留 hash/长度；tool output 默认不作为文本进入 store。已识别完成 tool surface 只形成 hash-only typed artifact；exact blob 仅限明确 allowlisted sanitizer 的小型非秘密输出。
- 捕获/读取/观察全都 fail-open：可选状态出错不能压制 L0 或阻断用户 turn。紧急隔离使用 `CODEX_CONTEXT_FABRIC_DISABLE=1`；完整配置回退须恢复已采用前的共享 `hooks.json`、`config.toml` 与 S 提交，而不是改写 append-only evidence。
- v1 Fabric store 需要显式 `migrate` 才可进入 `s.context_runtime.complete.v1`。迁移前像必须放在 live root 外、ACL 已先应用并回读的 S/B recovery sibling；迁移会在改变源库前重开并严格校验该前像。`restore-preimage` 可把它恢复到一个新/空 legacy target；current snapshot 的 `restore` 也只接受新/空且非链接 target。两种恢复都拒绝 source root 链接与 manifest 路径逃逸，先在同父目录 staging 校验，最后写 completion marker 并原子改名；它们仍不是外部 rollback anchor。

## 诚实采用口径

当前可声明的是：completion implementation 提供显式迁移、canonical/derived 分层、hash-only tool artifact、有界 trigger-scoped structural producers、原子 projection/run receipt、规范 UTC 的 bitemporal correction、受限 session-lineage、source-pinned materialize/rehydrate API，以及 staged snapshot/restore；这些局部谓词由仓库测试覆盖。每次用户纠偏会先作为原始事件留下；只有显式、source-linked 的 replacement/correction admission 才把它提升为当前语义关系，运行时不会靠“纠正”等关键词自行猜测。

尚不可把上述实现写成已通过的实际 fresh/compact/resume S/B consumer 行为，也不可声称 CurrentSituation 自动修订、自动恢复旧父活动、长期减少用户解释/纠偏负担，或形成“同一个持续认识者”。当前 verifier/restore 的 trigger、meta、derived-tamper、source-link 与 manifest-containment 回归已闭合，但它们只证明本地 tamper-evidence 与 staged recovery；防同账户/管理员改写、外部 rollback 检测和消费者恢复仍不成立。这些结论仍需 installed hook 的 fresh consumer readback 和后续真实轨迹验证。
