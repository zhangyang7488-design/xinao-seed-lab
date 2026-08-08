# Pi 0.84.1 main `prime` with an isolated PiB cold snapshot

S 只承载主 `prime` 与隔离 PiB 冷备的启动、投影、认证绑定、身体安装、验证和恢复胶水。Pi 自己的主体、功能、意图和演化正文不存放在这里：

- 共同 Pi 合同岛：`E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island`
- PiB 冷备表面岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island`
- 主 `prime` 活动表面岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island`

两份隔离 profile 都运行 Pi 0.84.1 和 Node 22.19.0+，但只有一个默认活动主体：

- `prime-s`：主 `prime` 的内部兼容 profile 名；账号可在干净边界切换，用户未限定地说 Pi 时默认指它。
- `prime-b`：`C:\Users\xx363\PrimeB.lnk` 指向的隔离冷备。当前边界一次性冻结主 `prime` 已证明的完整身体；完成后不随主面演化，也不进入例行维护、测试、报告或提起。

研究新澳和改进 Pi 自身都是主 `prime` 可以在同一个 active session 内开展的活动，不是角色、profile 或 session 类型。冷备复刻行为、能力器官、扩展、Pi-native 孩子与恢复链；不复刻 OAuth、`auth.json`、account binding、session、运行中孩子树、memory 数据、表面认知、活动状态或主快捷入口。它只在这次快照边界做 fresh 根/孩子验收，之后保持冻结。

每个 profile 内的 `account-binding.json` 只选择自己的 OAuth 来源。主 `prime` 可用 `Set-UpstreamPiAccountBinding.ps1 -Profile prime-s -Slot main|account-b` 在干净边界切换额度来源；它不改行为、Skills、session 或仓库。切换只替换 native `auth.json` 的 `openai-codex` 项；重启后的根与后续 OpenAI 孩子共同消费这一绑定，DeepSeek 等独立 provider 原样保留。PiB 保持自己的隔离绑定，普通账号切换不碰它。

主 `prime` 当前的稀疏身体还包括 profile-local Hermes memory/session anchors、默认冷置且空
server 的 MCP adapter、原生 Serper `web_search`、以及 native DeepSeek V4 Flash/Pro。
Luna、Terra 与 DeepSeek 的递归劳动都通过 `pi-subagents` child session 发生，不等于
Codex 外部 WorkerPool；具体任务是否调用某个器官仍由根 Pi 按真实信息收益选择。
PiS 的 `pi-subagents@0.44.0` 直接消费上游 portable workflow ID，不再为这条路径保留本地
改写；本地最薄兼容层只把 child `write` 回执中的 `/d`、`/mnt/d`、`/cygdrive/d` 在权威
输出路径比较时等价为 `D:\...`。它不放宽成功 write、精确目标、错盘或 sibling 输出的
authorship 边界；每次安装和启动都会做版本、源码 hash 与补丁 hash 校验，未知上游字节
直接拒绝。
Hermes 的 PiS 兼容层会跳过 `sessions\subagent-artifacts` 中的孩子 transcript 账本，避免
把它们误报成损坏的 Pi v3 session；账本本身保留，主 session 与孩子 session 均不删除。

默认用户入口是桌面 `prime.lnk`，经 Windows Terminal `prime` profile 和 `Open-Prime.ps1`
进入内部 `prime-s` profile。`C:\Users\xx363\PrimeB.lnk` 保留独立冷备入口；普通工作不枚举、
维护或提起它。旧 `Open-Prime-S.ps1` 只作内部兼容转发。

普通桌面启动使用 Pi 原生 `--continue`。事故恢复或精确返回时，
`Open-Prime.ps1 -Session <native-session-id|profile-local-session-file>` 可在主 profile 内恢复具名 session；
`-NewSession` 与 `-Session` 互斥，跨 profile 路径会拒绝。RPC/验收脚本默认使用
`--no-session`，不得污染桌面最近会话。

Codex 代用户执行可见 PiS 重启时，必须先在 ingress 上让精确实例到安全边界并 stop，再使用
`scripts\Start-PrimeSInWindowsTerminal.ps1 -Session <native-session-id>`。该入口强制选择
`prime` Windows Terminal profile，并先证明具名 session 正是该 profile 的最新 session，
再让原生 profile commandline 以 `--continue` 恢复；不通过 `wt.exe` 覆盖 wrapper commandline；
不得直接 `Start-Process pwsh ...Open-Prime.ps1`，因为那会保留 Pi 会话却把用户可见宿主降成
独立 conhost。启动回执仍只是请求证据，须从新 ingress 回读同 profile/session 与新 instance。

主 `prime` 还继承了旧 Pi 表面已经由用户真实确认的小键盘回车双语义，但没有沿用旧 Prime
动作名：`scripts\Set-PiSNumpadEnterFollow.ps1` 把物理 `NumpadEnter` 限定在标题为
`prime` 的 Windows Terminal 窗口。鼠标在底部输入区时发送普通 `Enter`；鼠标在输出区
时发送 `F12`，由 Pi 0.84.1 profile 的 `tui.altScreen.bottom` 消费，滚到输出末尾并恢复
跟随。原生 `End`、主键盘 `Enter` 和 Windows Terminal 全局键位均保持不变；
AutoHotkey 辅助由 launcher 隐藏启动并随 owner 退出，缺失或失败只降低这项便利，不能阻断
Pi 正常启动。`prime` profile 另外固定 `closeOnExit=always`：失败或已停止的 Pi
页签自动退场，不把“进程已退出”残页留给用户；它不作用于其他 Windows Terminal profile
或 Codex 页签。

主 `prime` 的 `activity-visibility.ts` 只改原生 working loader 的短文本：模型分析、证据读取、
计算/实验、孩子运行、工具失败、压缩和恢复都给出机械且诚实的自然中文活性提示。它不调用
第二个模型、不翻译或伪造隐藏思考，也不隐藏或替换原生 spinner、thinking、工具卡、FleetView
和 transcript；根 Pi 仍按合同在证据或路线实质变化时自己给出稀疏中文语义摘要。

主 `prime` 的可寻址通信由 profile-local `supervisor-ingress.ts` 和
`understand-and-steer-prime` Skill 提供，支持 exact instance/session 的 prompt、忙态
steer、follow-up、abort 与 stop。ACK 只是运输证据；必须继续回读 message consumed、
agent settled、native transcript 和真实效果。idle 投递会先越过 Pi 把 `isIdle` 置真但
`agent_settled` 尚未退栈的竞争窗口，防止只见 `runtime_accepted` 而正文未进入 session；
延迟期间若目标转为 busy，idle prompt 显式失败而不偷换成 steer。stop 先取消 ingress 自己尚未
消费的延迟/排队消息；其回执也只证明 shutdown 已请求，必须由 pipe/进程消失证明退出。重启后 instance 会改变，
旧目标请求失效。

初始化脚本会把共同合同岛与相应表面岛确定性合成为该 profile 的 `PI_CONTRACT.md`；launcher 每次启动前刷新该活动投影。profile 的 `AGENTS.md` 仍直接链接主 Codex 行为源，因此合同岛补 Pi 自己的关系，不复制第二套 Codex。

旧 Prime Agent 0.7.0 runtime/session 仅保留为离线迁移与回滚历史，不再是桌面 PrimeB 的活动产品。

`surface-overlays\prime-s` 保存主面的活动身体；`surface-overlays\prime-b` 保存这次明确授权的
冻结身体快照。两者在快照边界逐文件比较，随后独立投影到各自 profile。旧选择性晋升脚本仅作
历史兼容工具，不产生默认同步任务；账号、auth、sessions、memory、活动状态和整岛始终排除。

`scripts\Test-PiCrossRepositoryContext.ps1` 默认只验证主 `prime`；只有明确恢复冷备时才显式传
`-Profile prime-b`。探针用 fresh、no-session、只读工具实际读取新澳仓的 `AGENTS.md` 与
`STATUS.md`，验证跨仓连续性来自当前对象识别和局部语义恢复，而不是切换 Pi 身份或只让模型复述热合同。

`codex-skills\steward-pis-evolution` 是 Codex 侧的薄恢复/操作入口：它不复制 Pi 认知正文，
而是先回读共同合同岛与当前能力谱系，再按需进入真实 profile、通信边缘、身体实验室和消费者。
`scripts\Install-CodexPiSStewardSkill.ps1` 将这一源码确定性投影到主 Codex Skills；Account B
通过既有 `skills` junction 共同消费，不生成第二份配置源。

PiS 的 `gpt-5.6-sol` 上下文窗口由 profile 的 `models-store.json` provider catalog 决定；
`Set-PiSBodyConfiguration.ps1` 会精确移除 `models.json` 中同模型的本地 `contextWindow`
覆盖，同时保留其他 provider/model 自定义。`Test-UpstreamPiDualEntry.ps1` 会从活动 catalog
读回实际窗口并拒绝覆盖复发。当前观察值是 272000，但源码不把该漂移事实写死为未来上限。

Pi 0.84.1 的普通 auto-compaction 只在完整 agent run 结算后检查；一个持续调用工具的长回合
可以在中间追加 tool result 后立刻发出下一次 provider 请求，越过 `reserveTokens` 阈值。
`Apply-PiSMidTurnCompactionCompatibility.ps1` 在受管 profile 由 launcher 显式开启 gate 时，
复用 agent-core 已有的 `shouldStopAfterTurn`：在完整 tool result 边界估算
下一请求上下文，达到阈值则先结束当前 loop、调用原生 compaction，再从同一 durable session
的 tool result 继续。未带 gate 的普通 Pi consumer 保持 0.84.1 原行为。补丁按包版本、
上游源码 hash 与补丁 hash fail closed；`Test-PiSMidTurnCompaction.mjs` 使用本地确定性 provider
同时证明上游红例、PiS gate 绿例、同 session compaction 持久化、完成结果消费，以及“压缩被取消且
已有排队 steer”时仍不放行下一 provider 请求；各形态保留独立 receipt，不调用外部模型。
首次应用会保存并校验精确上游 preimage。回滚先停止活动 PiS，运行
`Restore-PiSMidTurnCompactionCompatibility.ps1`，再以
`Start-UpstreamPi.ps1 -Profile prime-s -DisableMidTurnCompactionCompatibility` 启动已恢复的上游核心；
普通 launcher/installer 会正式重新应用兼容层，不能在回退验证期间调用。恢复脚本只在当前字节等于
已知补丁 hash 或已知上游 hash 时工作，不能用 preimage 覆盖未知包字节。

核心候选不能直接在共享 Pi binary 上试验。`New-PiSBodyLab.ps1 -IsolatePiCore` 会在该 lab 下
安装独立的 pinned `pi-tool-root`；再加 `-ApplyMidTurnCompactionCompatibility` 才把候选补丁施加
到这份隔离核心。默认 body lab 不复制或修改共享核心。

`pi-subagents@0.44.0` 已由上游使用 portable workflow ID，不把 provider tool-call ID 当
目录；本地 Windows 兼容层仍闭合 file-only structured acceptance 路径，在比较孩子写入
归属时将 `/d`、`/mnt/d`、`/cygdrive/d` 视为同一 Windows 盘符路径。
错盘、sibling、失败/无回执 write、edit 与仅 prose 仍拒绝；安装和启动按版本及源码哈希
fail closed，不把路径兼容放宽成任意文件信任。
`scripts\Test-PiSFileOnlyAcceptanceRpc.mjs` 可在 fresh RPC 中重跑真实根 Pi -> operator child
链，核对 child session 的 `win32` 探针、唯一 `/d/...` write、structured acceptance 消费，
并在同一源码上重放上述负边界。
