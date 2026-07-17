# 工程意图解码 · 深度（温 · 按需 Read · 非 always）

SENTINEL:GROK_LIVE_FIELD_INTENT_DECODE_DEPTH_V1

**热层极短：** `.grok/rules/36-grok-live-field-intent-decode.md`
**合同：** `grok_live_field_intent_decode.v1.json`

## 动态取证（展开）

| 要 | 不要 |
|----|------|
| 状态/进度/inventory 先读本地 live | 念合同或外搜冒充已读现场 |
| 选型/新组件/陌生接缝短查权威源 | 脑内常识冒充已核对 |
| 高影响省略用成熟常形补全 | 写成长调研拖死当轮 |
| 让外部结果实际改变选择 | 搜了但仍照旧猜 |

**原则：** 本机事实与外部成熟都按问题取用；不固定任何一个永远先。

## 三角

1. **本机现状** — 当前对象、消费者、效果与偏差
2. **外部成熟** — 当技术选择或省略需要补全时轻量真搜
3. **口语线索** — 现场增量，不是离线完整规格

落点机制 = 解码之后，不得当标题。

## 做（全量）

1. 先归类：状态题本地优先；选型/高影响省略再轻量外搜
2. 解码旋钮与省略；拆开正交对象
3. **ACI 三拍**（工程向默认，借 SWE-agent 形状，不装整仓）
   - **读状态** — git/状态文件/进程/证据最新，先看真现场
   - **动手** — 改对的旋钮 / 真改仓
   - **再读现象** — 再跑或再读；stdout/状态变化才算 observation
4. 禁止「文件在 / 命令返回成功 / 测绿」代替现象

## 薄借外形成熟（不装第二 OS）

| 借 | 本机落点 |
|----|----------|
| SWE-agent ACI | 三拍 observation |
| Codified hot/cold | 热=L0/rule36/tier0；冷=施工包按需读 |
| Voyager 环 | 做→真跑→证据→再改 |
| Aider 味 | 真改仓+git；非替换主窗 |

## 交叉

rule `26`/`28` 成熟优先 · distill A01 · rule `91` · standing 中文

SENTINEL:GROK_LIVE_FIELD_INTENT_DECODE_DEPTH_READY
