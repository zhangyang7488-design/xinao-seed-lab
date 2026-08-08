# Pi 0.84.1 prime S primary surface with PrimeB minimum-usable baseline

S 只承载 PrimeB 与 prime S 的启动、投影、认证绑定、包安装、验证和选择性晋升胶水。Pi 自己的主体、功能、意图和演化正文不存放在这里：

- 共同 Pi 合同岛：`E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island`
- PrimeB 稳定表面岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island`
- prime S 领先实验岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island`

两个表面都运行 Pi 0.84.1 和 Node 22.19.0+，都直接消费主 Codex 的 AGENTS/Skills，但当前用途不对称：

- `prime-s`：默认绑定主 Codex，是当前主要工作与成熟化对象；另装冷置、显式调用的 `pi-autoresearch@1.6.2`。
- `prime-b`：默认绑定 Codex Account B，保留能理解意图、完成普通真实工作、调用有界子劳动并恢复的最低可用基线；安装 `pi-subagents@0.43.0`，但不追求与 prime S 对称优化。

研究新澳和改进 Pi 自身都是一个完整 Pi 可以在同一个 active session 内开展的活动，不是角色、profile 或 session 类型。prime S 是否可用和成熟由它自己的 fresh 消费者决定，不以 PrimeB 接收增量为完成门槛；PrimeB 仍有独立的最低真实工作能力完成尺，不能用“能启动”代替。只有某个已证明增量确有 B 侧消费者时，才做选择性晋升和 B fresh 验收。

每个 profile 内的 `account-binding.json` 只选择该表面的 OAuth 来源。`Set-UpstreamPiAccountBinding.ps1 -Profile prime-b|prime-s -Slot main|account-b` 不改另一表面、行为核、Skills、session 或仓库。切换只允许在该 profile 停止后发生，只替换 native `auth.json` 的 `openai-codex` 项；新启动的根 Pi 与后续 OpenAI 孩子共同消费这一 profile，DeepSeek 等独立 provider 原样保留。切换后的真实根/孩子验收仍必须重跑，脚本本身不把“写入成功”冒充消费成功。

prime S 当前的稀疏身体还包括 profile-local Hermes memory/session anchors、默认冷置且空
server 的 MCP adapter、原生 Serper `web_search`、以及 native DeepSeek V4 Flash/Pro。
Luna、Terra 与 DeepSeek 的递归劳动都通过 `pi-subagents` child session 发生，不等于
Codex 外部 WorkerPool；具体任务是否调用某个器官仍由根 Pi 按真实信息收益选择。
PiS 的 0.43.0 Windows 兼容补丁同时保证异步 workflow ID 不把 provider tool-call 字符带入
路径，并把 child `write` 回执中的 `/d`、`/mnt/d`、`/cygdrive/d` 仅在权威输出路径比较时
等价为 `D:\...`。它不放宽成功 write、精确目标、错盘或 sibling 输出的 authorship 边界；
每次安装和启动都会做版本、源码 hash 与补丁 hash 校验，未知上游字节直接拒绝。
Hermes 的 PiS 兼容层会跳过 `sessions\subagent-artifacts` 中的孩子 transcript 账本，避免
把它们误报成损坏的 Pi v3 session；账本本身保留，主 session 与孩子 session 均不删除。

用户入口分别是 `Open-Prime-Agent-Account-B.ps1` 与 `Open-Prime-S.ps1`，对应独立 Windows
Terminal profile；旧 `Open-Prime-Codex-Parity-Test.ps1` 只作无状态兼容转发，不再承担
“同一会话 parity mode”语义。

普通桌面启动使用 Pi 原生 `--continue`。事故恢复或精确返回时，
`Open-Prime-S.ps1 -Session <native-session-id|profile-local-session-file>` 可在本 profile 内恢复具名 session；
`-NewSession` 与 `-Session` 互斥，跨 profile 路径会拒绝。RPC/验收脚本默认使用
`--no-session`，不得污染桌面最近会话。

Codex 代用户执行可见 PiS 重启时，必须先在 ingress 上让精确实例到安全边界并 stop，再使用
`scripts\Start-PrimeSInWindowsTerminal.ps1 -Session <native-session-id>`。该入口强制选择
`XINAO prime S` Windows Terminal profile，并先证明具名 session 正是该 profile 的最新 session，
再让原生 profile commandline 以 `--continue` 恢复；不通过 `wt.exe` 覆盖 wrapper commandline；
不得直接 `Start-Process pwsh ...Open-Prime-S.ps1`，因为那会保留 Pi 会话却把用户可见宿主降成
独立 conhost。启动回执仍只是请求证据，须从新 ingress 回读同 profile/session 与新 instance。

prime S 还继承了旧 PrimeB 已经由用户真实确认的小键盘回车双语义，但没有沿用旧 Prime
动作名：`scripts\Set-PiSNumpadEnterFollow.ps1` 把物理 `NumpadEnter` 限定在标题为
`prime S` 的 Windows Terminal 窗口。鼠标在底部输入区时发送普通 `Enter`；鼠标在输出区
时发送 `F12`，由 Pi 0.84.1 profile 的 `tui.altScreen.bottom` 消费，滚到输出末尾并恢复
跟随。原生 `End`、主键盘 `Enter`、Windows Terminal 全局键位和 PrimeB 均保持不变；
AutoHotkey 辅助由 launcher 隐藏启动并随 owner 退出，缺失或失败只降低这项便利，不能阻断
PiS 正常启动。`XINAO prime S` profile 另外固定 `closeOnExit=always`：失败或已停止的 Pi
页签自动退场，不把“进程已退出”残页留给用户；它不作用于其他 Windows Terminal profile
或 Codex 页签。

prime S 的可寻址通信由 profile-local `supervisor-ingress.ts` 和
`understand-and-steer-prime` Skill 提供，支持 exact instance/session 的 prompt、忙态
steer、follow-up、abort 与 stop。ACK 只是运输证据；必须继续回读 message consumed、
agent settled、native transcript 和真实效果。idle 投递会先越过 Pi 把 `isIdle` 置真但
`agent_settled` 尚未退栈的竞争窗口，防止只见 `runtime_accepted` 而正文未进入 session；
延迟期间若目标转为 busy，idle prompt 显式失败而不偷换成 steer。stop 先取消 ingress 自己尚未
消费的延迟/排队消息；其回执也只证明 shutdown 已请求，必须由 pipe/进程消失证明退出。重启后 instance 会改变，
旧目标请求失效。

初始化脚本会把共同合同岛与相应表面岛确定性合成为该 profile 的 `PI_CONTRACT.md`；launcher 每次启动前刷新该活动投影。profile 的 `AGENTS.md` 仍直接链接主 Codex 行为源，因此合同岛补 Pi 自己的关系，不复制第二套 Codex。

旧 Prime Agent 0.7.0 runtime/session 仅保留为离线迁移与回滚历史，不再是桌面 PrimeB 的活动产品。

`surface-overlays\prime-s` 保存主工作面的 Pi-specific 候选；`prime-b` 只保存维持最低真实可用或有具名 B 消费者的已采用增量。
`Invoke-PiSelectivePromotion.ps1` 目前只允许单个 `agents/*.md` 或 `contract/*.md`，要求
候选 hash 和独立验收回执，先存 B preimage，再投影并跑 B fresh 验收；失败自动恢复。
`Restore-PiSelectivePromotion.ps1` 只在当前字节仍等于已晋升 hash 时回滚。两者都机械排除
auth、account-binding、sessions、整 profile 和整岛复制。包/launcher/runtime 变更不能冒充
这条文件晋升通道，必须另做相交实现与验收。

`scripts\Test-PiCrossRepositoryContext.ps1` 默认只验证 prime S；需要回退面证据时才显式传
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
`Apply-PiSMidTurnCompactionCompatibility.ps1` 只在 `XINAO_PI_PROFILE=prime-s` 且 launcher
显式开启 gate 时，复用 agent-core 已有的 `shouldStopAfterTurn`：在完整 tool result 边界估算
下一请求上下文，达到阈值则先结束当前 loop、调用原生 compaction，再从同一 durable session
的 tool result 继续。PrimeB 和未带 gate 的普通 Pi consumer 保持 0.84.1 原行为。补丁按包版本、
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

`pi-subagents@0.43.0` 的 Windows 兼容层同时闭合两条已复现路径：异步 workflow 使用独立
`workflow-UUID`，不把 provider tool-call ID 当目录；file-only structured acceptance 在
比较孩子写入归属时，将 `/d`、`/mnt/d`、`/cygdrive/d` 视为同一 Windows 盘符路径。
错盘、sibling、失败/无回执 write、edit 与仅 prose 仍拒绝；安装和启动按版本及源码哈希
fail closed，不把路径兼容放宽成任意文件信任。
`scripts\Test-PiSFileOnlyAcceptanceRpc.mjs` 可在 fresh RPC 中重跑真实根 Pi -> operator child
链，核对 child session 的 `win32` 探针、唯一 `/d/...` write、structured acceptance 消费，
并在同一源码上重放上述负边界。
