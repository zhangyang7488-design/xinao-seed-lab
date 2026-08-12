# Codex 薄情境上下文生产合同

`SENTINEL:THIN_SITUATION_CONTEXT_PRODUCTION_V1`

当前接入由薄情境观察与 S/B `Context Fabric` 第一版共同组成。它不声明已经制造持续主体，也不创建任务、路线、Owner、授权或完成状态。Context Fabric 的完整生产合同见 `S_CONTEXT_FABRIC_CURRENT.md`。

## 活动消费者

- `UserPromptSubmit` 调用 `scripts/codex_situation_context_hook.py`。输出先保留短
  `HUMAN_WORDS_BEFORE_ARTIFACTS_V2`，再按当前人话从 S/B 的 append-only conversation events 物化一份有 source event 的 bounded historical view；同 session 热尾优先，fresh session 才回退到同 carrier 热尾，跨 TUI 内容仍须由当前查询命中。最后附一份紧凑的机械
  `RuntimeObservation`。观察描述 Hook 子进程、实际 cwd、Git 与活动规则文件；事件自报字段另行标记，未测得的权限和工具面保持 `UNKNOWN`。
- `SessionStart(source=resume|compact)` 调用同一入口。它可从同一 S/B interaction world 读取 bounded recent/relevant conversation view，并读取当前 exact `session_id` 下已经显式写入的 provisional `CurrentSituation`。任一表面不存在、损坏、忙或过大就省略并继续；不得读取 task-run frontier 或恢复旧任务。
- `Stop` 只保存当前 surfaced assistant message；`PreCompact` / `PostCompact` / `SessionEnd` 只追加生命周期边界。它们不 block、不自动续跑、不写 CurrentSituation；compact 后的模型上下文仍由 `SessionStart(source=compact)` 单点物化。
- `scripts/manage_current_situation.py` 是唯一显式写入口。`NO_MATERIAL_CHANGE`
  不落盘；`MATERIAL_REVISION` 以 generation/hash CAS 替换 current，并把被替换前像写入冷 revision receipt。模型输出、历史记录或文件存在本身不会自动调用它。
  明确结束、换对象或被替代时用 `retire` 写 tombstone 和冷恢复回执；超过 7 天的
  checkpoint 不再热注入，需要重新显式建立。

S/B 两个账号载体通过共享的 `hooks.json`、`config.toml` 与 S 源码消费同一实现；只有账户凭证、session 与产品强制绑定的账户状态隔离。

## 权力边界

- CurrentSituation 始终 `provisional=true`、`authority=false`，只是一份当前世界的交接投影。
- checkpoint 是会被下一次模型调用看见的明文上下文；禁止写入 token、密码、API key、
  cookie 或其他秘密。它继承本机目录 ACL，不是跨 Windows 用户的秘密保险箱。
- session identity 只接受规范小写 UUID；session 目录或 current 文件的 link/redirect
  被拒绝，避免一个名字读取另一个 session。
- 当前用户整句话和 live facts 可立即替换 checkpoint；checkpoint 不能授权行动、证明完成或证明自主 world revision。
- RuntimeObservation 只报告机械事实。它不能从 cwd、仓库、文件名或状态生成任务。
- Context Fabric 的 raw user/assistant event 是发生证据；semantic projection、correction edge 和 materialized context 都是可重建、`authority=false`、`instruction_source=false` 的读取投影。疑似秘密只保留 hash/长度，tool output 不自动进入 store。
- Context Fabric 的 mount policy 只允许 S/B `CODEX_HOME`；unknown body 与 `E:\CODEX_CLEANROOM` cwd fail closed。CodexA/C、新仓库 Sol 与 fresh research session 不继承该历史。
- 旧 `session_start_continuity_pointer_v1.ps1`、binder、restore 与 Stop gate 继续作为冷恢复材料；新的 `resume|compact` reader 不消费它们，也不恢复其生命周期语义。

## 生产采用与回滚

正式采用需要同时成立：S 提交可定位、S/B `hooks/list` 发现并信任全部具名
Hook、直接 JSON-stdio readback 正确、event chain/SQLite readback 正确、fresh S/B carrier 能从上一 session 恢复精确标记、讨论负例不出生工具动作、明确行动仍可被识别、cleanroom negative mount 为空，以及 recovery v2 能从精确源重建当前载体。

紧急隔离先设置 `CODEX_CONTEXT_FABRIC_DISABLE=1`；完整回滚再恢复采用前的共享
`hooks.json`、`config.toml` 与 S 仓提交。旧 `user_prompt_zero_beat_v1.ps1` 保持原字节，可重新取得唯一活动 UserPromptSubmit 消费者身份。删除或停用 Context Fabric 不影响普通 Codex 工作；CurrentSituation 冷 revision 也不会被热读取。

当前工程完成只可声称：机械本地现实进入真实 S/B 消费者；admitted surfaced conversation 可 append-only 保存、按需重构；显式 checkpoint 能在 resume/compact 边界被 exact-session 读取。长期纠偏负担下降、自主修订和“同一个认识者”仍由后续真实轨迹验证。
