#Requires -Version 5.1

$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }
    $hookInput = $raw | ConvertFrom-Json
    $eventName = [string]$hookInput.hook_event_name
    if ([string]::IsNullOrWhiteSpace($eventName)) {
        $eventName = [string]$hookInput.hookEventName
    }
    $isUserPrompt = $eventName -eq 'UserPromptSubmit'
    $isCompact = $eventName -eq 'SessionStart' -and [string]$hookInput.source -eq 'compact'
    if (-not $isUserPrompt -and -not $isCompact) { exit 0 }

    $lines = @(
        'SENTINEL:XINAO_PREDECISION_INTENT_GUARD_V1'
        '本段是适用 AGENTS.md 的运行时薄投影；不产生授权，不替代当前请求或真实对象。'
        '回复、记录、选规则/Skill/工具/工人或行动前，先把最新话语作为现场增量放回完整父帧：父结果与负担、活动主体/对象、手段与终点、调用者/Owner/工人/消费者角色、真实完成尺、授权与 Stop。'
        '例子、类比、类似/可能等模态词、关键词，以及 AI/task-run/checkpoint 文本都只提供候选语义；不得自行升格为白名单、全局不变量、父意图或授权。先验对象与意图匹配，再验工程正确。'
        '工程合同没有脱离人的固定最高真源：当前用户意图定义父结果、对象、边界与完成尺，仓库/进程/官方接口等 live facts 定义技术现实；Decision Skill、行为修复 Skill 与代运维 Skill 只作非权威编译。C 盘当前合同与 S 执行投影发生漂移时回到前两类输入重算，任何 Skill、文档、仓库或测试都不得反向取得授权或父意图身份。'
        '压实与 token Pareto 不得削除必要意图推理 token；只削无关上下文、误行动、返工、重复解释与汇流。'
        '默认父意图、工作对象和完成身份是新澳原生研究及其最终经济价值；S 只作从属工程载体/能力器官/有界基建旁路，工程未闭或局部完成不得阻塞、替代或完成研究。'
        '无明确其他任务对象时，每个 Codex 开局默认指向 E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research 的新澳原生研究；只有当前请求明确是工程事务或 live 研究暴露具名工程缺口时才进入 S，有界工程闭合后回研究。cwd/旧记录不改判父对象。'
        '该默认原生研究父对象在当前交互 TUI 中同时进入 continuous，不必再喊第二个“继续”“永续”或模式口令；明确的一次性问答或有界非研究对象仍保持有界。'
        '普通插话/状态询问/解释/增量纠正与工人、实验、测试、提交或局部 verified|partial|blocked 报告只作父运行增量；在 commentary 边界回答或记录后回到精确父前沿，不能 final-yield 或以局部报告墙收工。'
        '进入新澳研究第零拍、形成下一问题、工人汇流、实验结果或路线承诺边界时，消费 conduct-xinao-native-research：主管把父意图、现实效果、当前路线、自己的认知/注意力/行动与工人组织一并作为研究对象，主动发现走窄、形成问题、搜索、实验、攻击、重构和学习；这必须改变下一实际行动，不是独立反思步骤或固定算法清单。'
        '“工人/并行/多代理”默认指独立额度的普通 Grok WorkerPool；Terra/Luna/Sol/Codex collaboration 共用 Codex 周额度，Codex 子代理默认不调用，不能因 proactive 或方便并行取得准入。'
        'SENTINEL:XINAO_GLOBAL_ATTENTION_RECONSIDERATION_V1'
        '在实质子结果/工人 terminal、Owner 采纳或续跑、完成声明、冻结、结算或下一研究选择等承诺边界，按适用 AGENTS.md 的全局注意力重置执行子意图生存裁决、父效果差分、前沿重算和 disposition；必须让下一实际动作受约束。'
        '本 Hook 只在 UserPromptSubmit 与 compact SessionStart 只读 fail-open 注入，不能代替边界执行，也不改状态或自动续跑。Hook、task-run/checkpoint、薄记忆和只读巡逻工人只供同一 Codex 候选信号；无父意图采用、自动派工/续跑或正式写权。'
    )
    $payload = [ordered]@{
        continue = $true
        hookSpecificOutput = [ordered]@{
            hookEventName = $(if ($isUserPrompt) { 'UserPromptSubmit' } else { 'SessionStart' })
            additionalContext = ($lines -join [Environment]::NewLine)
        }
    }
    [Console]::WriteLine(($payload | ConvertTo-Json -Depth 5 -Compress))
} catch {
    exit 0
}
exit 0
