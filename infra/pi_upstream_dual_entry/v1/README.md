# Versioned main `prime` compatibility body with an isolated PiB cold snapshot

这是本机 Pi 0.84.1 的日期化工程映射，只说明当前启动链、兼容补丁和已验证消费者；它不定义
Pi 的长期主体、模型、孩子拓扑、研究方式、主管关系或生命周期。当前官方 live 能力与当前人话
先于这里的实现记录。

S 只承载主 `prime` 与隔离 PiB 冷备的启动、投影、认证绑定、身体安装、验证和恢复胶水。Pi 自己的主体、功能、意图和演化正文不存放在这里：

- 共同 Pi 合同岛：`E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island`
- PiB 冷备表面岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island`
- 主 `prime` 活动表面岛：`E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island`

两份隔离 profile 都运行 Pi 0.84.1 和 Node 22.19.0+，但只有一个默认活动主体：

- `prime-s`：主 `prime` 的内部兼容 profile 名；账号可在干净边界切换，用户未限定地说 Pi 时默认指它。
- `prime-b`：`C:\Users\xx363\PrimeB.lnk` 指向的隔离冷备。当前边界一次性冻结主 `prime` 已证明的完整身体；完成后不随主面演化，也不进入例行维护、测试、报告或提起。

两者的 Pi 核心也物理隔离：主 `prime` 使用
`D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1`，PiB 冷备保留
`D:\XINAO_RESEARCH_RUNTIME\tools\pi\0.84.1`。所有 launcher、安装器和回归都从当前
profile spec 取得 `PiToolRoot/PiCommand`；不存在可同时改动两边的共享活动 command。

活动对象由当前人话和 live facts 决定；profile、session、仓库名或本说明不会创建研究/主管/执行角色。冷备复刻版本化能力、扩展、Pi-native 孩子与恢复链；不复刻 OAuth、`auth.json`、account binding、session、运行中孩子树、memory 数据、活动状态或主快捷入口。它只在这次快照边界做相交验收，之后保持冻结。

每个 profile 内的 `account-binding.json` 只选择自己的 OAuth 来源。主 `prime` 可用 `Set-UpstreamPiAccountBinding.ps1 -Profile prime-s -Slot main|account-b` 在干净边界切换额度来源；它不改行为、Skills、session 或仓库。切换只替换 native `auth.json` 的 `openai-codex` 项；重启后的根与后续 OpenAI 孩子共同消费这一绑定，DeepSeek 等独立 provider 原样保留。PiB 保持自己的隔离绑定，普通账号切换不碰它。

主 `prime` 当前的稀疏身体还包括 profile-local Hermes memory/session anchors、默认冷置且空
server 的 MCP adapter、原生 Serper `web_search`、以及 native DeepSeek V4 Flash/Pro。
Luna、Terra 与 DeepSeek 的递归劳动都通过 `pi-subagents` child session 发生，不等于
Codex 外部 WorkerPool；具体任务是否调用某个器官仍由根 Pi 按真实信息收益选择。
主 `prime` 另有 profile-local `peer`：它是 fresh、candidate-only、read-only 的无预分工
认识面，不预装 reviewer/operator/task-generator 职业，可直接重建继承的完整对象并形成或
拒绝局部问题。其长期默认模型是 Terra；根可按当次现实收益覆盖为 Sol，这不把临时额度口头
许可写成长期策略，也不转移当前 effect scope 的正式责任。
主 `prime` 还提供无固定职业的 `recursive-peer` 高容量面：`thinking=max`、模型继承当前根或由
根按任务显式覆盖，不把一次额度口头授权固化成长期 provider 路由；它只暴露原生 `subagent`，
不直接取得文件、shell、网络或写入工具，并由 capability ceiling 把所有后代继续锁为
`recursive-peer`。主面唯一执行形状是 typed `tasks:[...]`：一个批次 1–10 个 native child，
`concurrency` 1–6；省略 `async` 时前台执行，只有显式 `async:true` 才 detached。批次只有一份
顶层 `turnBudget`，每个 child 共同消费，`maxTurns + graceTurns` 必须在 10–30，省略即 30+0，
第 30 个 assistant turn 仍尝试工具时也会硬停，不能进入第 31 turn。

main profile 的递归深度为 3；同一 durable root session 的 descendant committed launch 累计上限
40；整棵 canonical child tree 同时最多 6 个 native Pi provider stream。根 Pi 不占这 6 个槽，
可继续综合，所以 provider 侧可观察到“根 + 最多 6 个孩子”。这些是可用上限，不是自动 fanout、
常驻任务或额度消耗目标。`workflowScript`、retained-child resume、external-cli、spawn-budget grant、
schedule 和 mission 在 capacity 模式中不可用；管理/Stop action 仍可用，已完成孩子最多保留 40 个
供 `children.list` 查看。PiB 冷备继续保留 2/32/4、8/4 和普通同步默认，绝不继承这套握手。

6/10/40 约束的是 canonical `pi-subagents` descendant tree，不是账号级配额或同一 Windows 用户下
恶意进程的 OS sandbox。深度、票据、provider 槽、轮次、Owner Stop、虚拟研究与 restricted
filesystem child 均 fail-closed；根仍按真实信息收益选择是否调用，不为烧额度制造任务。
PiS 的 `pi-subagents@0.44.0` 直接消费上游 portable workflow ID，不再为这条路径保留本地
改写；本地最薄兼容层只把 child `write` 回执中的 `/d`、`/mnt/d`、`/cygdrive/d` 在权威
输出路径比较时等价为 `D:\...`。它不放宽成功 write、精确目标、错盘或 sibling 输出的
authorship 边界；每次安装和启动都会做版本、源码 hash 与补丁 hash 校验，未知上游字节
直接拒绝。
Hermes 的 PiS 兼容层会跳过 `sessions\subagent-artifacts` 中的孩子 transcript 账本，避免
把它们误报成损坏的 Pi v3 session；账本本身保留，主 session 与孩子 session 均不删除。
主 `prime` 另外把 Hermes 的全局/失败记忆容量显式设为 10k/20k 字符，`USER.md` 与每个
project memory 仍各为 5k；overflow 继续 `reject`，不启用截断、FIFO、自动 consolidate 或
failure prompt 注入。这只增加 profile-local 的可检索存储余量，不增加模型上下文、首次 provider
请求或自动回忆。PiB 冷备不写三个 limit 字段，继续消费锁定依赖的 5k/5k/5k、failure 10k
默认值。`Test-PiSHermesMemoryCapacity.mjs` 在隔离主/冷备 body lab 中验证越过旧 10k 的写入、
超过 20k 的原子拒绝、Markdown/SQLite 逻辑一致、fresh-process search、prompt 不变与 PiB 字节
负例；它是采用/升级验收，不进入普通启动热路径。正式回执写到
`D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\acceptance\pi-hermes-memory-capacity-v1.json`。

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

主 `prime` 的可寻址通信端点是 profile-local `supervisor-ingress.ts`；操作说明与客户端位于
S 侧 `operator-tools/pi-native-ingress/`，不会作为 Skill 装进 Pi。它支持 exact instance/session 的 prompt、忙态
steer、follow-up、abort 与 stop。ACK 只是运输证据；必须继续回读 message consumed、
agent settled、native transcript 和真实效果。idle 投递会先越过 Pi 把 `isIdle` 置真但
`agent_settled` 尚未退栈的竞争窗口，防止只见 `runtime_accepted` 而正文未进入 session；
延迟期间若目标转为 busy，idle prompt 显式失败而不偷换成 steer。stop 先取消 ingress 自己尚未
消费的延迟/排队消息，并通过 `pi-subagents` 的 session-scoped RPC 同步立起新孩子启动栅栏，
停止同一 owner session 的 detached children 与 in-process workflow。detached child 只有在
`process-terminal.json` 已由真实 close observer 标为 `observed` 后才算 `stopped_observed`；
超时或证明缺失只返回 `partial/stop_unverified`，但明确 Stop 仍继续关闭根进程，不把验证失败
偷换成继续运行。等待窗口内若 child completion 意外触发新的 `agent_start`，supervisor 会再次
abort，防止根模型复起。stop 回执仍只证明 shutdown 已请求，必须由 pipe/根进程消失证明根退出。重启后 instance 会改变，
旧目标请求失效。

这条能力由主面专用 `Apply-PiSSubagentsSessionStopCompatibility.ps1` 按
`pi-subagents@0.44.0` 精确源码 hash 应用；补丁正文位于
`patches/pi-subagents-0.44.0-owner-session-stop.patch`。它在原生 RPC 内合并当前内存 job 与
磁盘 active run，按 session-file owner key 隔离，不让 supervisor 自己扫描临时目录或猜 UUID。
未知上游字节直接拒绝；PiB 冷备不随这次主面身体演化修改。主面的全局
`asyncByDefault=false` 与 `forceTopLevelAsync=false` 继续保留；这是生命周期/回收语义，不是
容量上限。`recursive-peer` frontmatter 的 `async:true` 只保留普通 single 兼容语义；主面的
capacity typed tasks 不继承 agent 级 async，省略时一律 foreground，只有根显式 `async:true`
才 detached，避免把 probe、verifier、operator 与 restricted single 无差别 detach。PiB 同样
保持普通同步默认。
Windows 上 detached runner 的 Stop 使用进程树终止而不是只杀 Pi writer，避免正在执行的 tool
后代变成孤儿；隔离 native Sol child 已实际启动长驻 Node 后代，并证明 Stop 后后代 PID 消失、
runner close 被观察、状态为 stopped，且并发新 launch 被 fence 拒绝。可重放验收脚本是
`Test-PiSubagentSessionStopProcess.mjs`，当前源码绑定回执位于
`D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\acceptance\pi-subagents-owner-session-stop-v2.json`。

主 `prime` 的 `pi-subagents@0.44.0` 还提供 opt-in、单任务作用域的
`filesystemPolicy`。在高容量主面，它只有一个 root-only 入口：恰好一个 typed task，加顶层
policy；必须使用原生 read-capable `peer`，不能使用只有递归工具的 `recursive-peer`：

```json
{
  "tasks": [{
    "agent": "peer",
    "task": "只读取安全投影并返回候选认识"
  }],
  "filesystemPolicy": {
    "allowedRoots": ["D:\\safe-projection"],
    "deniedPaths": ["D:\\safe-projection\\private"],
    "bash": "deny"
  },
  "turnBudget": {"maxTurns": 20, "graceTurns": 0}
}
```

省略 `async` 时它走 foreground native single；显式 `async:true` 才 detached。task `count>1`、
两个 task、item-level policy、policy 与 list/status/其他 action 混用、descendant/direct/RPC 注入，
以及 worktree、external-cli、structured output、显式 output/file-only、share、gate、acceptance
verify/review 都在创建 session、reserve ticket 或发 provider 请求前拒绝。容量后代的 schema
根本不暴露 policy；普通无 capacity 握手的 legacy FS workflow 只保留在兼容回归里，不是主 Pi
当前模型入口。

policy active 时只暴露 `read/grep/find/ls`；`bash` 固定拒绝，未知或自定义 file-capable 工具也
拒绝。相对路径从 child cwd 解析；Windows 盘符大小写和分隔符归一化，已存在目标按 realpath
验证，因此 `..`、绝对越界、symlink/junction 越界均被阻断。`grep/find/ls` 的搜索根若是
denied subtree 的祖先，会整次阻断而不是过滤结果；`grep` 的内容 regex 不是路径，只有 glob
参与路径检查，`find` 才检查 path pattern，`ls` 没有 pattern 字段。孩子可见错误只说明阻断
类别，不回显越界 canonical target。

restricted launch 强制 `--no-context-files --no-skills`、`context=fresh`、`maxSubagentDepth=0`
和 managed temp artifacts；agent 默认的 project context、skills、memory 或项目 artifactDir
不能覆盖。规范化 policy、digest、cwd、effective preload、depth、artifact dir 与 launch digest
进入 detached descriptor/status/result；resume 必须从 single-run durable surfaces 得到同一
policy/digest，任一 marker 缺失、冲突或 descriptor 缺失都 fail closed。policy payload、payload
hash、强制 runtime loader、gate module 的 path/hash 任一缺失或漂移，也在 provider 请求前拒绝。

这是一条路径能力边界，不是文本语义 redaction：如果一个已允许文件内部同时含有不应交给孩子的
语义，路径 policy 无法隐藏其中一段。根必须先生成只含安全内容的 projection，并只 allow 这个
projection 目录；不能把混合敏感文件加入 allowedRoots 后期待 policy 按内容删减。它也不是
Windows OS sandbox：同一用户身份下的恶意本地代码、并发路径替换、TOCTOU 和 hardlink alias
不在这条模型误搜防线的保证内；需要这类对抗隔离时必须使用操作系统级边界。

可重放 package 顺序固定为 surface overlay projection → Windows compatibility →
owner-session-stop → filesystem-policy → high-capacity；core 顺序为 midturn → native continuation →
high-capacity provider gate。恢复严格反序，先退 high-capacity，再退 FS/native 及其下层。每一层
只接受精确前像、自己的 final 或已知完整 downstream-composed final；二次 Start 只验证，不会
把 capacity-final 反向覆盖。Start、Install 和 `New-PiSBodyLab.ps1` 只在 `prime-s` 接这层，并且
每次启动先清空 static/binding/ticket 环境，只有 package/core/source/active hash 与本机
`node:sqlite` transaction probe 全部通过后才注入 static handshake。PiB 永不调用、永不注入，
也不得出现 capacity runtime、schema 或 registry。
主 `prime` 的可见进程在完整生命周期同时持有 profile instance mutex 与 high-capacity transaction
mutex；即使显式禁用 MidTurn/capacity，仍在同一临界区重新验证 underlay、保持 handshake 关闭，
并阻止运行期间替换 package/core 字节。两个写型安装器在 Initialize、npm install 或任何 patch
之前取得同一组锁；活动 Pi 存在或另一个事务占用时直接 fail closed，不会先写一半再报告 busy。

先在新 body lab 运行 `Test-PiSFilesystemPolicyAcceptance.ps1 -AgentDir <lab-agent-dir>`。验收使用
本地 stub provider，但通过真实 Pi RPC 跑 foreground、detached/resume、stale repair、Stop、
no-policy 对照、pre-context 攻击、junction 和 pre-provider 负例；每个具名 child toolResult 的
`toolCallId/toolName/isError/result hash` 与 transcript path/hash 都进入源码绑定 receipt。正式回执
路径是 `D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\acceptance\pi-subagents-filesystem-policy-v1.json`。
应用到主面后必须用 final 源码重跑这份验收；旧 owner-stop process receipt 不能代替它。

临时回滚前先停止活动主 Pi，并且只在 15 个文件仍全部等于已知 FS final 时，对 package root 运行
`git -c core.autocrlf=false apply --reverse --check <filesystem-policy.patch>` 后再 `apply --reverse`，
随后用 Windows 与 owner-stop 脚本 `-VerifyOnly` 证明精确 owner baseline。普通 launcher/installer
会重新应用 FS 层，因此回滚验证期间不要调用它们；未知字节或半态不得用补丁覆盖。

主 `prime` 另有 profile-local、root-only 的 `return_to_parent` 一次性传输工具。根 run 以
`local_boundary` 标记局部边界，以不透明 `activity_context_ref` 绑定产生事实时的活动上下文，并用
`returned_fact` 携带精确文本或序列化 JSON。工具先返回普通 tool result；当且仅当同一 run 以
`stopReason=stop` 干净结算时，才发送一次带唯一 arm id 的 native custom follow-up。arm 在投递后
消费，普通 prompt、resume 和以后 run 不继承它。

这条能力要求 launcher 在每次启动前先清除继承的
`XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE`，依次验证 MidTurn underlay 与 native abort fence 后，才给
实际主 Pi 进程设置 handshake。缺 handshake、`PI_SUBAGENT_CHILD=1`、Stop/abort/error/length/shutdown
时扩展保持 inert 或清除当前 arm；孩子仍以 subagent result 返回根。核心 fence 同时覆盖 agent_start
后与 provider 调用紧前的 abort，避免 follow-up 已入队后 Stop 又逃出一次新请求。它不调用
`sendUserMessage`，也不建立 timer、daemon、任务队列或跨重启接管。

`Apply-PiSNativeContinuationCompatibility.ps1` 只接受完整 MidTurn final 或完整 native final；重复
Start 时 MidTurn 层只验证 exact downstream-composed 三文件组合，不把它反向改回 underlay。回滚必须
先 `Restore-PiSNativeContinuationCompatibility.ps1`，再
`Restore-PiSMidTurnCompactionCompatibility.ps1`，混合或未知 hash 一律拒绝。机械 faux provider 与
持久 session 轨迹已经覆盖多-provider run、post-enqueue Stop、TUI/print、context 清理和 live parser
歧义负例；正式采用后仍必须 fresh 重启，并由真实 `gpt-5.6-sol` 自主调用一次再验 live parser。
在此之前它只是 `ADOPT_CANDIDATE`，旧同-run live 正例不能冒充原生 post-final 成熟。

初始化脚本会把共同合同岛与相应表面岛确定性合成为该 profile 的 `PI_CONTRACT.md`；launcher 每次启动前刷新该活动投影。profile 的 `AGENTS.md` 仍直接链接主 Codex 行为源，因此合同岛补 Pi 自己的关系，不复制第二套 Codex。

旧 Prime Agent 0.7.0 runtime/session 仅保留为离线迁移与回滚历史，不再是桌面 PrimeB 的活动产品。

`surface-overlays\prime-s` 保存主面的活动身体；`surface-overlays\prime-b` 保存这次明确授权的
冻结身体快照。两者在快照边界逐文件比较，随后独立投影到各自 profile。旧选择性晋升脚本仅作
历史兼容工具，不产生默认同步任务；账号、auth、sessions、memory、活动状态和整岛始终排除。

`scripts\Test-PiCrossRepositoryContext.ps1` 默认只验证主 `prime`；只有明确恢复冷备时才显式传
`-Profile prime-b`。四个彼此独立的 fresh、no-session 合成用例只开放 `read`，并要求实际读取
活动 `PI_CONTRACT.md` 与新澳仓 `AGENTS.md`、`README.md`。验收从 JSONL 工具事件核对精确读取，
以 AB/BA 镜像、局部结算和开放关系控制验证热语义；不调用新澳数据命令，也不保存长 transcript。

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
首次应用会保存并校验精确上游 preimage。若 high-capacity/native continuation 已应用，回滚先停止活动 PiS，依次运行
`Restore-PiSHighCapacityCompatibility.ps1 -AgentDir D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s -PiToolRoot D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1`、
`Restore-PiSNativeContinuationCompatibility.ps1 -PiToolRoot D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1` 与
`Restore-PiSMidTurnCompactionCompatibility.ps1 -PiToolRoot D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1`，再以
`Start-UpstreamPi.ps1 -Profile prime-s -DisableMidTurnCompactionCompatibility` 启动已恢复的上游核心；
普通 launcher/installer 会正式重新应用兼容层，不能在回退验证期间调用。恢复脚本只在当前字节等于
已知补丁 hash 或已知上游 hash 时工作，不能用 preimage 覆盖未知包字节。

`Install-PiSMainCore.ps1` 幂等安装并验证主 `prime` 的独立 0.84.1 核心；它要求对应 main
AgentDir 已有 FS-final package，并把 high-capacity package/core 作为一个原子事务接上。主核心另选择性
回移上游 `c185d412...` 的 DeepSeek `max_tokens` 修复和 `18dee5f0...` 的 fullscreen
全宽行快路；`Apply-PiSPost0841UpstreamCompatibility.ps1` 只允许主核心或隔离 body lab，
明确拒绝冷备核心。`Test-PiSPost0841UpstreamCompatibility.mjs` 以无网络 payload 捕获证明
内置及 custom DeepSeek 都发送 `max_tokens`，并比较修补前后中文可见输出。回滚使用
`Restore-PiSPost0841UpstreamCompatibility.ps1 -PiToolRoot <main-root>`，随后必须 fresh 重启；
PiB 不应用这两笔主面增量。

核心候选不能直接在主或冷备的受管 Pi binary 上试验。`New-PiSBodyLab.ps1 -IsolatePiCore` 会在该 lab 下
安装独立的 pinned `pi-tool-root`；再加 `-ApplyMidTurnCompactionCompatibility` 才依次把 MidTurn、
native continuation 与 high-capacity package/core 候选补丁施加到这份隔离身体。默认 body lab 不复制或修改主核心或冷备核心，
也不设置 runtime handshake；验收进程只在核心与扩展 hash 都已读回后显式注入。

Pi profile 的 `shellPath` 是 Git Bash。丢弃输出使用 `/dev/null`，不能写 `NUL`；后者会在
Git Bash 中创建真实未跟踪文件。研究或身体变更到自然边界时回读相交仓库工作树，精确清除
已证工具副作用，不把广目录扫描或清理仪式化。

`pi-subagents@0.44.0` 已由上游使用 portable workflow ID，不把 provider tool-call ID 当
目录；本地 Windows 兼容层仍闭合 file-only structured acceptance 路径，在比较孩子写入
归属时将 `/d`、`/mnt/d`、`/cygdrive/d` 视为同一 Windows 盘符路径。
错盘、sibling、失败/无回执 write、edit 与仅 prose 仍拒绝；安装和启动按版本及源码哈希
fail closed，不把路径兼容放宽成任意文件信任。
`scripts\Test-PiSFileOnlyAcceptanceRpc.mjs` 可在 fresh RPC 中重跑真实根 Pi -> operator child
链，核对 child session 的 `win32` 探针、唯一 `/d/...` write、structured acceptance 消费，
并在同一源码上重放上述负边界。
