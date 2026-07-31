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
        '压实与 token Pareto 不得削除必要意图推理 token；只削无关上下文、误行动、返工、重复解释与汇流。'
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
