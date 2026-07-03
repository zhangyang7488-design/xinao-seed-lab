# Grok 详包不可降级（自动注入 · 每次投递）

SENTINEL:GROK_INTENT_PACKAGE_NON_DOWNGRADE_RULE_V1

**用户已恢复：** 换新 S 窗后 anti-shrink 合同丢失；本规则与 JSON 重新焊死。

**合同：** `grok-admin-bridge/grok_intent_package_non_downgrade_contract.v1.json`

## 冻结语义

- Grok 双投递的 **semantic_object + user_intent_cn + expected_state = 执行合同**，不是建议稿。
- Codex **不得**擅自缩水、换对象、把并行改成只读盘点、用 verifier/总账代替 diff/invoke。
- **唯一合法降级：** 任务包或 WORKER_ASSIGNMENT **明示** `serial_boundary`，或磁盘 **named_blocker** 含原因+解阻动作。

## 典型缩水（段审直接 fail_partial）

- 3 只读子代理「盘点」代替迁移/薄绑
- `Waiting for agents` 挂机当进展
- docs/current 总账、verifier 马拉松无 S 代码 diff
- 把 Grok 纠偏包当背景忽略

## Grok 投递

每次 `Send-GrokIntentToCodexA` **自动注入** `grok_intent_package_non_downgrade_ref`；禁止 Grok 自己先缩包再投。

SENTINEL:GROK_INTENT_PACKAGE_NON_DOWNGRADE_RULE_READY