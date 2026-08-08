# Pi 0.84.1 prime S primary surface with PrimeB minimum-usable baseline

S 只承载 PrimeB 与 prime S 的启动、投影、认证绑定、包安装、验证和选择性晋升胶水。Pi 自己的主体、功能、意图和演化正文不存放在这里：

- 共同 Pi 合同岛：`E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island`
- PrimeB 稳定表面岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island`
- prime S 领先实验岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island`

两个表面都运行 Pi 0.84.1 和 Node 22.19.0+，都直接消费主 Codex 的 AGENTS/Skills，但当前用途不对称：

- `prime-s`：默认绑定主 Codex，是当前主要工作与成熟化对象；另装冷置、显式调用的 `pi-autoresearch@1.6.2`。
- `prime-b`：默认绑定 Codex Account B，保留能理解意图、完成普通真实工作、调用有界子劳动并恢复的最低可用基线；安装 `pi-subagents@0.43.0`，但不追求与 prime S 对称优化。

研究新澳和改进 Pi 自身都是一个完整 Pi 可以在同一个 active session 内开展的活动，不是角色、profile 或 session 类型。prime S 是否可用和成熟由它自己的 fresh 消费者决定，不以 PrimeB 接收增量为完成门槛；PrimeB 仍有独立的最低真实工作能力完成尺，不能用“能启动”代替。只有某个已证明增量确有 B 侧消费者时，才做选择性晋升和 B fresh 验收。

每个 profile 内的 `account-binding.json` 只选择该表面的 OAuth 来源。`Set-UpstreamPiAccountBinding.ps1 -Profile prime-b|prime-s -Slot main|account-b` 不改另一表面、行为核、Skills、session 或仓库。

用户入口分别是 `Open-Prime-Agent-Account-B.ps1` 与 `Open-Prime-S.ps1`，对应独立 Windows
Terminal profile；旧 `Open-Prime-Codex-Parity-Test.ps1` 只作无状态兼容转发，不再承担
“同一会话 parity mode”语义。

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
