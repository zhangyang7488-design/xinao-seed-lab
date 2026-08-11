# Codex 薄情境上下文生产合同

`SENTINEL:THIN_SITUATION_CONTEXT_PRODUCTION_V1`

这次接入只提供三个小帮助，不声明已经制造持续主体，也不创建任务、路线、Owner、授权或完成状态。

## 活动消费者

- `UserPromptSubmit` 调用 `scripts/codex_situation_context_hook.py`。输出先保留短
  `HUMAN_WORDS_BEFORE_ARTIFACTS_V2`，再附一份紧凑的机械
  `RuntimeObservation`。观察描述 Hook 子进程、实际 cwd、Git 与活动规则文件；事件自报字段另行标记，未测得的权限和工具面保持 `UNKNOWN`。
- `SessionStart(source=resume|compact)` 调用同一入口。它只读取当前 exact
  `session_id` 下已经显式写入的 provisional `CurrentSituation`。不存在、损坏或过大就省略并继续；不得枚举 session、按时间选择“最新”、读取 task-run frontier 或恢复旧任务。
- `scripts/manage_current_situation.py` 是唯一显式写入口。`NO_MATERIAL_CHANGE`
  不落盘；`MATERIAL_REVISION` 以 generation/hash CAS 替换 current，并把被替换前像写入冷 revision receipt。模型输出、历史记录或文件存在本身不会自动调用它。
  明确结束、换对象或被替代时用 `retire` 写 tombstone 和冷恢复回执；超过 7 天的
  checkpoint 不再热注入，需要重新显式建立。

Account A/B 通过共享的 `hooks.json`、`config.toml` 与 S 源码消费同一实现；只有账户凭证、session 与产品强制绑定的账户状态隔离。

## 权力边界

- CurrentSituation 始终 `provisional=true`、`authority=false`，只是一份当前世界的交接投影。
- session identity 只接受规范小写 UUID；session 目录或 current 文件的 link/redirect
  被拒绝，避免一个名字读取另一个 session。
- 当前用户整句话和 live facts 可立即替换 checkpoint；checkpoint 不能授权行动、证明完成或证明自主 world revision。
- RuntimeObservation 只报告机械事实。它不能从 cwd、仓库、文件名或状态生成任务。
- 旧 `session_start_continuity_pointer_v1.ps1`、binder、restore 与 Stop gate 继续作为冷恢复材料；新的 `resume|compact` reader 不消费它们，也不恢复其生命周期语义。

## 生产采用与回滚

正式采用需要同时成立：S 提交可定位、A/B `hooks/list` 发现并信任两个具名
Hook、直接 JSON-stdio readback 正确、讨论负例不出生工具动作、明确行动仍可被识别，以及 recovery v2 能从精确源重建当前载体。

回滚时只需恢复采用前的共享 `hooks.json`、`config.toml` 与 Situation Island
README preimage；旧 `user_prompt_zero_beat_v1.ps1` 保持原字节，可重新取得唯一活动
UserPromptSubmit 消费者身份。删除或停用 current checkpoint 不影响普通 Codex 工作；冷 revision 不会被热读取。

这次完成只可声称：机械本地现实进入真实 A/B 消费者，以及显式 checkpoint 能在
resume/compact 边界被 exact-session 读取。长期纠偏负担下降、自主修订和“同一个认识者”仍由后续真实轨迹验证。
