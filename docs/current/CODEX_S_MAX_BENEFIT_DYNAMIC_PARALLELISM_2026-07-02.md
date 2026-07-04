# Codex S 最大收益动态并行 readback

SENTINEL:CODEX_S_MAX_BENEFIT_DYNAMIC_PARALLELISM_20260702

## 现在能干什么

最大并行已经从“开多少 Codex/DeepSeek/search lane”落成 Phase 0 顶层对象：FrontierCandidate、FrontierPortfolioSnapshot、LaneResultReview、RewardSignal。调度目标是当前 frontier 的边际收益，不是 lane 数。

- 桌面源稿已记录：exists=False chars=None sha256=None
- 候选数：12
- Codex slots 观测值：6，只作为当前 Codex lane class 容量输入，不是全局并行上限。
- DeepSeek 本窗口尝试 shards：24，named blocker=DEEPSEEK_DRAFT_ADAPTER_UTF8_SURROGATE_BLOCKER，不得缩回 6。
- ArtifactAcceptanceQueue：accepted=1，staged=None，rejected=None，blocked=None，只表示 NextFrontier evidence，不是事实晋升。
- Resource allocator queue telemetry：artifact_accepted=1，artifact_blocked=0，deepseek_fan_in_decisions=0，deepseek_fan_in_staged=0，deepseek_fan_in_rejected_no_verifier=0。
- Temporal runtime activity refs：runtime_enforced_count=2，adoption_state=verifier_ready_but_activity_refs_missing_or_not_enforced，只限 activity-level evidence，不是 Stop hook/controller/completion gate。
- Scheduler invocation packet activity：activity_runtime_enforced=False，activity_scope=，base_packet_runtime_enforced=False，default_runtime_scheduler_invoked=False，spawned_lane_count=1，named_blocker=。
- Durable packet actual dispatch refs：worker_ref_count=0，derived_from_worker_activity=False，entry_id_count=0。
- Durable packet service/API/CLI entrypoint：api_cli_adoption_state=api_cli_verifier_ready_not_hook_enforced，gateway_provider=True，runtime_enforced=False，service_state_ref=C:\Users\xx363\AppData\Local\Temp\pytest-of-xx363\pytest-2203\test_cli_invokes_default_main_0\runtime\state\durable_parallel_wave_packet\service_entrypoint_latest.json。
- Main-loop tick service/API/CLI entrypoint：api_cli_adoption_state=api_cli_verifier_ready_not_hook_enforced，gateway_provider=True，runtime_enforced=False，service_state_ref=C:\Users\xx363\AppData\Local\Temp\pytest-of-xx363\pytest-2203\test_cli_invokes_default_main_0\runtime\state\codex_s_main_execution_loop_tick\service_entrypoint_latest.json。
- Default main-loop trigger candidate：adoption_state=missing_or_not_run，api_cli_adoption_state=missing_or_not_run，gateway_provider=True，trigger_installed=False，runtime_enforced=False，service_state_ref=C:\Users\xx363\AppData\Local\Temp\pytest-of-xx363\pytest-2203\test_cli_invokes_default_main_0\runtime\state\default_main_loop_trigger_candidate\service_entrypoint_latest.json。
- Seed Lab user-correction runtime service refs：api_cli_adoption_state=api_cli_verifier_ready_not_hook_enforced，gateway_provider=True，selection_read_model_visible=True，scheduler_invoked=False，trigger_installed=False，runtime_enforced=False，service_state_ref=C:\Users\xx363\AppData\Local\Temp\pytest-of-xx363\pytest-2203\test_cli_invokes_default_main_0\runtime\state\seed_lab_user_correction_runtime\service_entrypoint_latest.json。
- DP search open/citation verifier：attempted=False，checks=0，opened_or_checked=0，accepted_claims=0，paid_provider_invoked=False，claim_span_prepared=False，claim_span_artifact_accepted=False。

## 证据路径

- D 盘 latest：`C:\Users\xx363\AppData\Local\Temp\pytest-of-xx363\pytest-2203\test_cli_invokes_default_main_0\runtime\state\max_benefit_dynamic_parallelism\latest.json`
- D 盘中文 readback：`C:\Users\xx363\AppData\Local\Temp\pytest-of-xx363\pytest-2203\test_cli_invokes_default_main_0\runtime\readback\zh\max_benefit_dynamic_parallelism_20260702.md`
- E 盘 repo readback：`E:\XINAO_RESEARCH_WORKSPACES\nianhua-new-route-active\docs\current\CODEX_S_MAX_BENEFIT_DYNAMIC_PARALLELISM_2026-07-02.md`
- 验证入口：`tests/seedcortex/test_max_benefit_dynamic_parallelism.py` 和 `scripts/verify_max_benefit_dynamic_parallelism.ps1`

## Top Frontier

- `fc-fan-in-acceptance-queue` utility=27.7372 expected=3.9722 reasons=evidence_acceptance_gate,prevents_report_only_stop
- `fc-supervisor-loop-state-schema` utility=27.0259 expected=3.6259 reasons=critical_path,schema_first,high_unblock_value
- `fc-lane-result-review-contract` utility=25.0528 expected=3.0678 reasons=producer_reviewer_verifier_auditor_modeled
- `fc-deepseek-surrogate-blocker-repair` utility=23.2897 expected=2.2547 reasons=named_blocker,code_path_sanitizer_repair_verified,deepseek_width_not_codex_slot_bound,unblocks_large_width_sidecar
- `fc-source-family-next-wave` utility=22.4233 expected=1.3133 reasons=minimum_exploration_budget,source_family_coverage

## 资源分配

- Codex：read/write/merge/verify/side-audit/repair 六类 slot，按 frontier utility 分配。
- 默认并行：任何 frontier edge 先按可并行处理；只有 same-file write、merge、fan-in acceptance、事实晋升、强依赖或不可回滚风险才串行。
- DP sidecar：draft/eval/contradiction/extraction/audit/search/citation_verify/provider_probe 都是子执行 mode；DP search 是其中的搜索 mode，不是 DP 端口定义本身。
- DeepSeek/local/provider：多路子执行可大宽度 dispatch，小批量 acceptance，剩余 staging。
- Search：official/GitHub/community/papers/local evidence 继续 source-family waves；DP search 已接入 CapabilityGateway、SourceLedger、ClaimCard 和 fan-in acceptance，静态 smoke 不冒充 live search。
- MetaMinute：final/PASS/report 前和开新并行波前保留 60 秒认知预算语义；可提前通过，但必须字段完整且下一机器动作非空，不能缩水成 0 秒 checklist。
- Codex search/subagents 是默认开放研究 lane；DP sidecar execution 是 durable 子执行端口，DP search 只是该端口的搜索补充 lane，不是最大并行定义本身。
- Live search 私钥位置：`C:\Users\xx363\私钥` 或 `D:\XINAO_RESEARCH_RUNTIME\private\search.env`；原始 key 不写入 repo/log/readback。
- Human-visible：中文 readback 是 heartbeat，不是 final。

## Evidence Acceptance

Evidence acceptance 是晋升门，不是落文件。draft -> ClaimCard -> verified claim -> code/test/policy/evidence/readback/blocker；每段都要求 refs 和 verification_need，file_exists_sufficient=false。

## 不能声明

- 不能声明 Phase 0 已完成。
- 不能把默认执行退回单 lane 串行；串行必须有 same-file/merge/acceptance/dependency/risk 之一的命名理由。
- 不能声明 DeepSeek draft 已被 Codex fan-in 采纳；当前 fan-in acceptance 结果是 accepted=0、staged_candidate=1、rejected_no_verifier=7。
- 不能声明 DP search 结果已变成事实；当前只允许通过 SourceLedger/ClaimCard/fan-in acceptance 晋升。
- 不能把 static provider smoke 说成 live 外部搜索；live provider 由私钥/env 探针决定。
- 不能把 report/PASS/latest.json 当停止条件。
- 不能把私人/小众开源直接升格为事实源或默认能力。

## 下一机器动作

- SupervisorLoopState.parallelism_governor selection is bound into Seed Cortex episode/WorkflowPort evidence and canonical ArtifactAcceptanceQueue now accepts verified artifacts as NextFrontier evidence; next bind queue counts into resource allocator telemetry.
- Use Codex fan-in acceptance output on the 8 staged DeepSeek ClaimCards: accepted=0, staged_candidate=1, rejected_no_verifier=7.
- Focused verifier/artifact delta for the staged supervisor candidate is recorded as a Codex-owned domain contract; keep rejected drafts as reusable negative evidence.
- MetaMinute / PreflightReflection is now a runtime checkpoint with 60-second cognitive budget semantics and early-exit completeness checks; run it before final/report/PASS wording and before each new parallel wave.
- DeepSeek DP search is routed through CapabilityGateway -> SourceLedger -> ClaimCard -> fan-in acceptance; open/citation checks, zero-cost ledger, claim-span evidence, and ArtifactAcceptanceQueue NextFrontier acceptance are bound without fact promotion.
- Live external DP search keys are auto-loaded from C:\Users\xx363\私钥 or D:\XINAO_RESEARCH_RUNTIME\private\search.env; if none are found, keep DP_SEARCH_PROVIDER_NOT_CONFIGURED as named blocker and do not pretend static smoke is live search.
- Continue source-family waves for official/GitHub/community/papers/local evidence; do not official-only shrink.
- Attach reward signals to future ReplayEvalResult/StrategyUpdate without starting Phase 1 data chain.

SENTINEL:XINAO_MAX_BENEFIT_DYNAMIC_PARALLELISM_READY
