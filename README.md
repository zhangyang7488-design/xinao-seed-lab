# Xinao Market Lab

这是主线 P1/P2 的独立工程核，不是下注产品、预测服务或第二套 Agent 平台。

P1 保留原始可验收纵切；P2 在不改写 P1 账本的前提下增加来源目录、lineage-v2、8 个
类型化精确号码投影、136 行全分类和哈希链纯结算验收；P3 再增加先冻结后执行的有限
ResearchProtocol 与 JudgeGate；P4 再加一个严格冻结的五检验联合原假设与来源污染门；P5
把仍未解决的返还/特码两面 49 语义做成完整的 33 文件 scan-or-exclude 证据目录：

1. 只读扫描并哈希 `C:\Users\xx363\Desktop\主线\新澳数据包`；canonical 运行只允许把证据写到 `D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab`；
2. 钉死来源、开奖对象、特码结算和含本成本口径；
3. 对最多四个在本次执行前固定的机械基线生成确定性、追加式 `trials.jsonl`；
4. 报告均匀分布与理论 RTP 基线；
5. 前后重算输入哈希，拒绝任何主线或数据包回写。

P2 额外保留 136/4,043 条来源候选，纠正 `2023004/2024004` 的顺序依赖 lineage 问题，
并把开奖身份限定为七个号码而不是派生的波色/生肖标签。规则束覆盖 特码 A、正码 A、
正1特..正6特 A；8 条规则都从 full-v3 的 01..49 模态页取证，报价分别为 47.285、7.850、
42.300。独立语义 hash 将投影与报价/返还口径分离；返还口径、标签玩法和特码两面 49
政策仍是 `UNRESOLVED`，编译器不得猜测。

P3 把现有 4 个机械候选 × 8 条规则冻结为 32 个 cell 和 38,528 条 trial，显式钉住 4 个
时间序 fold、预算、规则/成本/输入/决策/输出 hash 以及 previous_hash。Judge 可以给出
`MECHANICS_ACCEPTED`，但在 payout、历史价格、Quote/Fill 和来源真值缺失时必须同时给出
`ECONOMIC_CLAIM_BLOCKED`；不会生成候选排名或“赢家”。

P4 不重排 P3 cell。它先在 raw 1,209 行上精确复现 5 条 lineage-v2 隔离记录，再只对
canonical 1,204 行执行 `T_special/T_pos_max/T_regular_incl/T_lag1/T_fold` 五项联合 6+1
Monte Carlo 原假设。所有检验共享 `PCG64` 的 19,999 条模拟流，plus-one p 与 Holm 都用精确
分数；完整模拟统计写入哈希链账本，`p4-verify` 会从头重模拟。污染门和 raw collision 诊断
不进入 Holm；结构原假设无论保留还是拒绝，经济声明仍被阻断。

P5 只处理 P2 中精确的两条 `UNRESOLVED` RuleClaim：`payout_basis` 与
`special_two_sided_49_policy`；136/16/120 分类表作为独立表面逐行核对，不制造第三条
RuleClaim。27 项文本/结构化来源使用严格 RFC 6901 与 W3C TextQuote/TextPosition 选择器，
6 项不适合作语义证据的文件仍保留哈希和排除理由。当前完整扫描只找到泛化的
`赔付=1/输赢=1/结算=18`，没有直接口径或 49 政策证据，因此终态必须是
`EVIDENCE_CATALOG_VERIFIED + SEMANTICS_STILL_UNRESOLVED + ECONOMIC_CLAIM_BLOCKED`。

赔率材料只有 2026-05-12 的单时点候选快照。历史开奖又全部带
`verify=false`，因此本工程只验证机械语义和复现性，禁止把结果表述为历史可交易 edge、
投注建议或真实资金动作。

P6 将公网采集与正式验收物理分开：一次只读 GET 四个精确官方 HTML URL，写入 D 盘
不可覆盖的 WARC/1.1 与外置 capture anchor；之后 A/B 和 p6-verify 全部离线消费同一
冻结 bundle。PJ 公告只支持窄的 MACAU_OFFICIAL_PRODUCT_CLAIM_REJECTED，DICJ 保留
reference-only 边界，HKJC 永远是 non-operator comparator，w1.kka8f.com 不联网且
精确域名法律状态不作判断。两条 RuleClaim 仍未解决，经济、排名、推荐和真实资金门继续关闭。

业务 L0 的 `l0-next-draw` 只在 lineage-v2 的 canonical 1,204 行上取最近 300 行，预先固定
扩窗频率、100 期滚窗频率和一阶 Markov 三项 49 类薄模型。六个时间前推窗统一报告
multiclass log loss、Brier、top-5 精确二项区间和三项 BH 校正；模型不过门就回退每号
`1/49`，不强行给号码排序，注额固定为 0。`l0-next-draw-verify` 会从原始只读输入独立重算
全部语义产物并核对代码指纹与文件哈希。

## 成熟模块边界

- Polars：带显式列类型读取 CSV/JSONL，并做表级统计；
- Pydantic：冻结且严格的领域对象、版本化规则束、结构化 `UNRESOLVED` 与账本记录；
- SciPy：P1 描述性卡方基线；NumPy：P4 直接锁定的 PCG64 联合 6+1 模拟；
- warcio 1.8.1：P6 仅用作 WARC/1.1 薄载体；安全 GET、边界和 SHA-256 锚由本工程控制；
- Hypothesis + pytest：结算、无泄漏和确定性不变量；
- uv：锁定 Python 依赖。

Pandera 的官方文档仍说明 Polars 后端不如 pandas 后端成熟；DVC、PyArrow、
statsmodels、MLflow、Ray、Iceberg/Delta 在当前 10 MB 级只读纵切没有正收益，均延后到
出现可观察的规模、协作或格式触发器。

## 运行

```powershell
$env:UV_CACHE_DIR = 'D:\XINAO_RESEARCH_RUNTIME\cache\xinao-market-lab\uv'
uv sync --dev --locked
uv run xinao-market-lab p1 `
  --input-root 'C:\Users\xx363\Desktop\主线\新澳数据包' `
  --evidence-root 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs' `
  --run-name 'p1-acceptance-a'

uv run xinao-market-lab p2-rule-catalog-pure-settle `
  --input-root 'C:\Users\xx363\Desktop\主线\新澳数据包' `
  --evidence-root 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs' `
  --run-name 'p2-acceptance-a'

uv run xinao-market-lab p3-research-protocol-judge `
  --input-root 'C:\Users\xx363\Desktop\主线\新澳数据包' `
  --evidence-root 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs' `
  --p2-evidence-run 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p2-rule-catalog-acceptance-a-20260711' `
  --run-name 'p3-acceptance-a'

uv run xinao-market-lab p4-exact-null-contamination-structure `
  --input-root 'C:\Users\xx363\Desktop\主线\新澳数据包' `
  --evidence-root 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs' `
  --p3-evidence-run 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p3-research-protocol-acceptance-a-20260711' `
  --run-name 'p4-acceptance-a'

uv run xinao-market-lab p5-unresolved-semantics-evidence-catalog `
  --input-root 'C:\Users\xx363\Desktop\主线\新澳数据包' `
  --evidence-root 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs' `
  --p4-evidence-run 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-exact-null-contamination-structure-acceptance-a-20260711' `
  --p4-trusted-anchor 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-exact-null-contamination-structure-trusted-anchor-20260711.json' `
  --admin-acceptance 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-admin-acceptance-20260711\admin_acceptance.json' `
  --run-name 'p5-acceptance-a'

uv run xinao-market-lab l0-next-draw `
  --input-root 'C:\Users\xx363\Desktop\主线\新澳数据包' `
  --evidence-root 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\l0-next-draw' `
  --run-name 'biz-l0-a-<unique>'

uv run xinao-market-lab l0-next-draw-verify `
  --input-root 'C:\Users\xx363\Desktop\主线\新澳数据包' `
  --run-dir 'D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\l0-next-draw\biz-l0-a-<unique>'
```

运行目录包含输入快照、数据审计、对象/规则钉死、136 行分类、试验账本、24 条哈希链
conformance events、候选汇总、均匀/RTP 基线与输出哈希。这里的“执行前固定”不是面向统计
推断的正式预注册；重复验收应在两个空目录运行，并要求 `trials.jsonl` 与
`conformance_events.jsonl` 分别字节完全相同。
