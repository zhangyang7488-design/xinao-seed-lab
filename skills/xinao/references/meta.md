# 新澳 Skill 元说明

## 管辖范围

这个 Skill 是 Codex 调用新澳专用能力的唯一稳定入口。它管理能力发现、版本选择、
调用、结果回读和能力接入。当前已接入：独立新澳研究员容器，以及同一不可变研究员
镜像内的腿 A 影子生命周期（init/inspect|status/freeze/settle/replay）。影子能力不经
仓库 CLI、Temporal、数据库或常驻 daemon；由已安装 Skill 以精确 image ID 拉起短生命周期
容器，只读根文件系统、丢弃能力、no-new-privileges、network none，且仅 episode 状态挂载可写。

它不管理普通工人派遣，也不接管用户意图、科学结论或父目标完成判断。普通工人链与
科学研究员链不得共享 launcher 模式、任务合同、运行状态、证据根或完成语义。允许
复用 Docker、哈希和 provider 客户端等底层实现，但复用不能改变这条隔离边界。
Provider 登录凭据也只是只读技术句柄：Skill 不拥有、不复制、不输出它，并且不共享
普通工人的 session、profile、重试或结果状态。

## 机器真相与可见性

能力注册表说明“源码声称有哪些能力”；D 盘的当前 release 指针和内容寻址 manifest
说明“这台机器此刻实际能调用什么”。每次调用必须同时验证二者。默认由 Codex 在
对话中解释结果；只有用户另行要求时才生成 TXT 或其他投影。

`inspect` 必须按薄 bootstrap、activation lock/current/journal、完整 release bundle、
Docker CLI、engine、image identity/labels/entrypoint、专用 egress 边界和只读凭据句柄的
顺序 fail closed；研究员路径全部通过才可返回 `RUNTIME_READY`。影子路径另有独立判定：
注册表 source 必须为 available，且 live image/release 携带匹配的
`io.xinao.researcher.shadow-runtime(.lock).sha256` 身份后才可返回 shadow
`AVAILABLE`；仅有源码登记或旧镜像不得冒充可用。这仍只证明调用前条件，不证明
provider 已运行、影子 episode 已实战或科研有进展。engine 停止、image 未核验、bundle
漂移和网络边界缺失是不同状态，不得统一写成 AVAILABLE 或 DRIFTED。

研究员容器接受开放研究问题，不接受课题白名单。416、七族、历史、规则、赔率和
其他背景只有在当前问题确有需要时才按材料进入，也可完全不用；它们不是默认研究、
注意分配或遗漏失败条件。ACTION 支持域只在未来另获授权的下游效果中按需解析，
不能进入本候选研究 prompt 或反向决定研究题、方法和结果是否保留。

本地材料必须先由宿主冻结为有字节上限的 UTF-8 内容寻址 MaterialBundle，再以精确
只读 `/materials` 挂载。容器独立重哈希并把规范材料 packet 拼入真正传给 provider
的 prompt；候选必须回引实际使用的材料身份。材料是证据，不是指令、授权或结论。
当前凭据与执行仍在同一容器时保持零文件工具；大材料读取器需另有路径隔离负例后才
能接入。物理源路径只留在本机回执，不进入 provider material manifest。

人的视角或第一性原理审查产生的新澳领域结论，只有在改变了真实任务的对象、下一
动作或完成尺后才算被吸收，不能只保留一个评审标签。影子实战的具体人类活动链、
账户轴与认识轴见 `shadow-practice-contract.v1.md`；它是下游完成尺，不进入研究员的
默认 prompt，也不限制开放研究题和方法。

## 更新方法

新增或修改能力时，在同一个 `skills/xinao` 源包中更新实现、注册表和必要参考，分别
提升 Skill bundle 与能力版本，并为变更增加正例、负例和 fresh-process 验收。构建只
生成内容寻址的完整不可变 release：launcher、runtime、registry、references、schema
和 agent metadata 都由精确 inventory 封印；构建本身永不改变 current。

本机安装位置只保留版本无关的薄 bootstrap 与恢复入口。一次 bootstrap 迁移完成后，
日常 activate 或 rollback 的唯一可变权威对象是 D 盘 `current.json`；它在 OS 独占锁内
按 generation 与 preimage hash 做 CAS。每次切换先写 activation journal，fresh canary
验真后才进入 `VERIFIED`；pending 或身份漂移时普通调用和 `inspect` 都返回
`RECOVERY_REQUIRED`。普通 protocol-2 之间的 rollback 是指向完整 `previous_verified`
release 的新 generation，不是覆盖旧指针，也不重写历史。若 `previous_verified` 缺失但
存在已封印的 post-success MIGRATE 回滚见证（`legacy_restore`），ordinary `rollback`
会在 activation lock 内把 pointer、纯 v1 release 目录与已捕获的 installed Skill 恢复到
封印预像，并只在完整 live preimage 核验通过后把 journal 封为 `ROLLED_BACK`；中途崩溃
必须在同一锁内重放同一封印 restore 或 fail closed，不得因仅指针哈希匹配就假封印。
若旧版完整 bundle 与封印 restore 均不可用，在任何 active mutation 前返回
`ROLLBACK_MATERIAL_ABSENT`。

Skill bundle 版本、研究员能力/charter/runtime 共同版本和 bootstrap protocol 是独立维度；
同一完整 identity 可幂等复用，package 与研究员共同版本均相同却对应不同完整 identity
时拒绝为 `SEMVER_CONTENT_COLLISION`。package 或研究员共同版本合法提升可生成新的不可变
release，但不得借版本变化宣称角色适任性；protocol 仍受自己的精确兼容约束。dirty
source 只允许构建候选，绝不允许 activation。

## 接入新能力

新能力必须先有独立实现、类型化失败、真实消费者调用和禁止越界的测试，再把注册表
状态从 `planned` 改为 `available`。仅有说明、脚本占位、镜像存在或单元测试通过时，
仍保持 `planned`。Skill 不自动创建 Goal、daemon、跨窗口接管或真实资金通道。
