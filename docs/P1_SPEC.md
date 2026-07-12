# P1 可验收纵切

## 输入与权限

- 唯一输入根：`C:\Users\xx363\Desktop\主线\新澳数据包`；
- 所有输出必须在 D 盘 evidence 根的新目录；
- 运行前后递归重算相对路径、大小和 SHA-256；
- 不解压回原目录，不修正源数据，不把候选解析表改写成“权威价”。

## 对象与规则

- `series_id=macaujc2_daily_2132_type8`；`upstream_key=macaujc2`；`type=8`；
- 每行 6 个正码加第 7 个特码，号码在 1..49 且期内不重复；
- `expect=2023004/openTime=2024-01-04` 是已知异常，必须隔离出顺序回放；
- 完全重复的七球结果只保留第一次，后续重复行隔离出顺序回放和均匀基线；
- 上游 `verify=false` 只表示数据未获独立确认，不可静默升级；
- 特码 A 盘展示倍数 47.285 来自 2026-05-12 单一候选快照，按“含本总返还”只验证机械口径；
- 赢：`selection == special`；输：不等；精确号码没有 push；
- `net = gross_return - stake - explicit_cost`，P1 `stake=1`、显式额外成本为 0。

## 执行前固定的机械基线

最多四个，顺序固定：

1. `always_no_bet`；
2. `fixed_01`；
3. `previous_special`；
4. `rolling_mode_49`（同频取最小号码）。

所有决策只能读取当前行之前的可用开奖。账本不含壁钟时间，两个独立输出目录的
`trials.jsonl` 必须字节相同。

这些基线是在 P1 执行前固定以防本轮继续扩搜索空间，但并非独立、公开、先于观察数据的统计
预注册，不能据此做显著性或 edge 宣称。

## 验收

- 包内 manifest 全哈希一致；TSV/JSONL 共同字段逐行一致；
- 1209 条源开奖、1203 条机械回放、136 条玩法结构、4043 条赔率候选；
- 结算 golden 和 Hypothesis 不变量通过；
- `always_no_bet` stake/gross/net 全为 0；
- 理论均匀 RTP 为 `47.285 / 49`；卡方值只作描述；
- 输入前后快照 ID 一致；两个账本 SHA-256 一致；
- 最终状态只能是 `verified_mechanics_only`，不包含 edge、投注建议或真实资金宣称。
