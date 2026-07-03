# Codex S MetaMinute / PreflightReflection readback

SENTINEL:CODEX_S_METAMINUTE_PREFLIGHT_REFLECTION_20260702

## 当前作用

MetaMinute 已落成 runtime checkpoint。它保留“一分钟元思考”的认知预算语义，但不是机械 sleep；只有结构化字段完整且下一机器动作非空时才允许提前通过。

- trigger：`window_start_first_hop`
- intended_cognitive_budget_seconds：60
- actual_elapsed_seconds：0.0001
- early_exit_allowed：True
- early_exit_reason：structured_fields_complete_and_next_machine_action_non_empty
- completeness_check_passed：True
- 当前对象：Codex S global self prelude verifier
- 最新用户增量：ordinary task without productivity keyword
- 下一机器动作：restore current route, L0, boundary contract, default parallel policy, and choose the highest-EV next machine action
- continue_or_named_blocker：continue
- 全局 Codex self-prelude：Codex S 全局自检前置：先把自己从审查/报告/守门人模式拉回执行图。看到用户意图后，第一反应是找现在能交付的 artifact：diff、capability invoke、ClaimCard、evidence 或 named blocker。测试和 readback 只是推进证据，不是停点。能推进就推进；撞到真实阻塞才命名 blocker。

## 证据路径

- D latest：`D:\XINAO_RESEARCH_RUNTIME\state\metaminute_preflight_reflection\latest.json`
- 全局 self-prelude latest：`D:\XINAO_RESEARCH_RUNTIME\state\codex_s_global_self_prelude\latest.json`
- 全局 self-prelude prompt：`D:\XINAO_RESEARCH_RUNTIME\state\codex_s_global_self_prelude\latest.prompt.md`
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
