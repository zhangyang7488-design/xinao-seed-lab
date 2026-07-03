# 新系统读序 + 禁 closure 默认（自动注入）

SENTINEL:GROK_AUTHORITY_READ_ORDER_FORBIDDEN_CLOSURE_RULE_V1

**读序权威：** `C:\Users\xx363\Desktop\新系统\AUTHORITY_READ_ORDER.txt`  
**机器合同：** `grok-admin-bridge/grok_authority_read_order_contract.v1.json`  
**禁包形状：** `grok-admin-bridge/grok_forbidden_intent_package_shapes.v1.json`

## 投递前

- 层 0 根意图 → 层 1 333 → 层 2 两份总稿（`桌面\新系统\`）→ 层 3 work_id
- 禁 `phase0_default_hot_path_full_closure` 当默认续跑包
- 新包投递须要求 Codex **换** `worker_assignment.source_intent_package_ref`
- 喊宽度前先读 driver/ledger latest

## 用户口令

「跑 333」「333续跑」「按新系统读序」= 层 1+2 续跑，不是全盘扫描

SENTINEL:GROK_AUTHORITY_READ_ORDER_FORBIDDEN_CLOSURE_RULE_READY