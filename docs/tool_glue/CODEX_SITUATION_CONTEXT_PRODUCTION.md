# Codex 薄情境上下文生产合同

`SENTINEL:THIN_SITUATION_CONTEXT_PRODUCTION_V1`

当前接入由薄情境观察、`CurrentSituation` checkpoint 与 S/B `Context Fabric` 组成。它们都只提供受限、可失败的证据；不创建持续主体、任务、路线、Owner、授权、Stop 或完成状态。Fabric completion 合同见 `S_CONTEXT_FABRIC_CURRENT.md`。

## 当前消费者与兼容期

- `UserPromptSubmit` 通过 `scripts/codex_situation_context_hook.py` 先保留 `HUMAN_WORDS_BEFORE_ARTIFACTS_V2`。当 hook child 的真实 cwd 位于 canonical S 工作体内时，紧接着加入 `TEXTUAL_WORLD_IS_EVOLVING_COGNITION_V1`：系统文本首先是认识随时间形成的外化切片，时序只作为回穿对象、理由、人的纠偏、现实变化和重新综合的认识指针，不是较新 artifact 自动覆盖较旧 artifact；缺失的关键对话保持为轨迹缺口，后来的成熟综合须吸收早期真实原因，后来的模板不能靠形式取得认识。随后加入 `CURRENT_RESULT_CONTROLS_ACTION_V1`：第一次选 Skill/工具/工人、扩大范围或准备停止前，把当前人话的真实结果、对象、消费者和刚好充分完成事实重新送入动作选择；上述关系都在内部改变下一动作，不能生成表格、版本争权、权限/ACL、supersession 门禁、计划或第二控制面。随后 Fabric 捕获当前 prompt 但在本次 readback 中排除它；加入有 source refs 的 bounded historical materialization，最后附机械 `RuntimeObservation`。观察只描述 hook child、cwd、Git 和活动规则文件；自报字段仍分开标记，未观测的权限/工具面保持 `UNKNOWN`。
- `SessionStart` 由同一 Fabric hook 捕获、记录 session-lineage node，并在 `resume|compact` 时尝试加入 bounded Fabric view。S 工作体内的 resume/compact immediate continuation 会先重新收到同一 L0、diachronic-cognition 与 action-binding 投影，避免 compact 边界静默丢掉认识演化或动作位阶；S 外部仍不挂载这些 S 投影。只有 Fabric 无法形成该视图时，才回退读取当前 exact `session_id` 下已经显式写入的 provisional `CurrentSituation`；不会双重注入两个 current view。任一可选表面忙、损坏、过大或不满足策略时均省略并继续。
- `Stop` 捕获 surfaced assistant message，并只对当前闭合 round 运行有界 structural producer；它不使用 `decision:block` 强制每轮再跑一次，因为固定续轮会把普通任务重新制度化。`PreCompact` 仅捕获边界；`PostCompact` 与 `SessionEnd` 捕获边界后只运行该边界的 structural segment/current-seed producer。完整历史 replay 只能由显式 manager/recovery 操作执行，不能进入 3–5 秒 hook 热路径。没有 hook 会自动写 CurrentSituation、推断语义纠偏、恢复 task frontier、续跑旧工作，或让 lineage node 授权 continuation。
- Mounted `SessionStart`、`Stop`、`PostCompact`、`SessionEnd` 完成上述同步工作后，只异步请求一次无窗口 Scheduled Task on-demand run；hook 自身不扫描 rollout。持续 controller 也只在状态原子落盘后请求同一任务。任务内部做有界稳定重试，15 分钟 trigger 仅作漏唤醒/崩溃/完整性复查兜底；因此 TUI 关闭不会留下尾段，空闲时也不再每两分钟扫描。

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

已经有一条受限的 installed-hook fresh/compact/resume 轨迹和一组 enabled-versus-empty fresh contrast，也有自动 rollout consumer 的真实任务回读；它们只证明这些具名路径上的行为，不证明唯一因果或长期收益。仍不可声称 CurrentSituation 自动修订、自动恢复旧父活动、长期减少用户解释/纠偏负担，或形成“同一个持续认识者”。防同账户/管理员改写与外部 rollback 检测也仍不成立。
