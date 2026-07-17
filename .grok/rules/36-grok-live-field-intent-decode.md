# 工程意图解码（always · 极短）

SENTINEL:GROK_LIVE_FIELD_INTENT_DECODE_RULE_V2

**合同：** `grok_live_field_intent_decode.v1.json`
**核心名：** **工程意图解码**
**长文：** 温层 `rules-on-demand/warm/36-grok-live-field-intent-decode-depth.md`（触及再 Read）

## 主句（分型，禁一律先外搜）

| 类型 | 序 |
|------|-----|
| **状态/进度/对账/inventory** | 口语 → **本机现状** → 现象校验 |
| **选型/方法/新组件/焊路** | 外部当前事实会改变选择时：口语 → **轻量外搜** → 本机现状 → 拆旋钮 → 现象；否则本地直接做 |
| **高度省略且改验收形状** | 口语 → **轻量外搜补全** → 本机现状 → 现象（不跳过本地） |

## 硬钉

| 要 | 不要 |
|----|------|
| ACI：读状态→动手→再读现象 | 文件在/命令成功/测绿当效果 |
| 状态类 **先本地工具** | cite-first：先背合同/规则名 |
| 选型类真外搜（短查） | rg 冒充外搜；外搜冒充已读现场 |
| 常形/验收/反模式 | 调研长文拖死当轮 |

**禁：** 字面优先 · 旋钮折叠 · 选链路线战 · 假完成 · 整装 SWE-agent/Aider 当主脑 · **禁止把「禁 rg 冒充外搜」读成禁止本地盘点**。

SENTINEL:GROK_LIVE_FIELD_INTENT_DECODE_RULE_READY
