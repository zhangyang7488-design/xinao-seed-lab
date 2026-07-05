# Codex S MetaMinute / PreflightReflection readback

SENTINEL:CODEX_S_METAMINUTE_PREFLIGHT_REFLECTION_20260702

## 当前作用

MetaMinute 已落成 runtime checkpoint。它保留“一分钟元思考”的认知预算语义，但不是机械 sleep；只有结构化字段完整且下一机器动作非空时才允许提前通过。

- trigger：`before_final_pass_report`
- intended_cognitive_budget_seconds：60
- actual_elapsed_seconds：0.0001
- early_exit_allowed：True
- early_exit_reason：structured_fields_complete_and_next_machine_action_non_empty
- completeness_check_passed：True
- 当前对象：Codex S Stop hook final/PASS/report surface
- 最新用户增量：不要停，继续监工后台
- 下一机器动作：check completion wording against fan-in acceptance and side-audit evidence; continue if not accepted
- continue_or_named_blocker：continue
- 全局 Codex self-prelude：Codex S 全局自检前置：先把每条用户话语判定为 human_dialogue / diagnosis / execution / watch，再决定是否进入 333。对话、讨论、只读诊断不启动主链、不制造 worker evidence；cwd/project/Seed Cortex 身份不能把对话自动升级成 execution；execution 才进入 RootIntentLoop / S Default Dynamic Loop；后台耐久事务/333/默认主链同义，不是 rescue、report、latest 或 worker lane。轮询/盯后台/监工/后台镜像/不要停表示当前前台 turn 进入 foreground mirror watch；333 后台耐久事务还活时，报告可以输出；报告后的 Stop hook 检查后台/live-watch 证据；后台活或仍有 backlog/source gap/next frontier/blocker 时继续短中文心跳、poll/kick/resume，不把状态报告当 final。文本/worker/readback 写着未完成、还缺、待接线、未固化、下一步时，默认锚定这些缺口继续派发/repair/bind，不能停在报告。非平凡工程缺口默认外部成熟搜索或子代理成熟发现；工程改动默认固化进 333，不需要用户二次提醒；未固化必须明说原因、缺的 binding 和下一机器动作。Stop/final/report/PASS/readback/latest 都不能冒充完成。

## 证据路径

- D latest：`D:\XINAO_RESEARCH_RUNTIME\state\metaminute_preflight_reflection\latest.json`
- 全局 self-prelude latest：`D:\XINAO_RESEARCH_RUNTIME\state\codex_s_global_self_prelude\latest.json`
- 全局 self-prelude prompt：`D:\XINAO_RESEARCH_RUNTIME\state\codex_s_global_self_prelude\latest.prompt.md`
- 意图解码索引 latest：`D:\XINAO_RESEARCH_RUNTIME\state\codex_s_intent_decode_index\latest.json`
- E repo 意图解码索引：`E:\XINAO_RESEARCH_WORKSPACES\S\docs\current\CODEX_S_INTENT_DECODE_INDEX_2026-07-05.md`
- D 中文 readback：`D:\XINAO_RESEARCH_RUNTIME\readback\zh\metaminute_preflight_reflection_20260702.md`
- E repo readback：`E:\XINAO_RESEARCH_WORKSPACES\S\docs\current\CODEX_S_METAMINUTE_PREFLIGHT_REFLECTION_2026-07-02.md`
- 验证入口：`tests/seedcortex/test_metaminute_preflight_reflection.py` 和 `scripts/verify_metaminute_preflight_reflection.ps1`

## 不允许

- 不允许把它变成 prompt-only 的“冷静一分钟”。
- 不允许把它缩水成 `metaminute_seconds=0` 或普通 checklist。
- 不允许把它变成 completion gate、事实源或执行控制器。
- 不允许用旧 A/B/C/CLEAN gate 覆盖 S 当前对象。
- 不允许在 final/report/PASS 前跳过 fan-in acceptance。

## 成熟模式吸收

- `react_reason_then_act` -> pre-action reasoning field before tool/action dispatch
- `reflexion_feedback_then_next_round` -> failure or feedback checkpoint before retry
- `self_refine_iterative_feedback` -> structured self-feedback as candidate signal, not completion
- `tree_of_thoughts_expand_then_evaluate` -> multiple next-action candidates before selecting highest EV
- `langgraph_interrupts_persistence` -> checkpointed interrupt/resume boundary, not chat-only pause
- `temporal_durable_execution_for_ai` -> durable workflow boundary for long agent loops
- `autogen_reflection_critic` -> critic/reflection lane before and after action
- `openai_agents_guardrails` -> composable input/output checks that do not swallow the user goal

SENTINEL:XINAO_METAMINUTE_PREFLIGHT_REFLECTION_READY
