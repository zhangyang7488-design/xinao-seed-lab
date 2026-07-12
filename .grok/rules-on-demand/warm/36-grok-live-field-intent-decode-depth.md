# 工程意图解码 · 深度（温 · 按需 Read · 非 always）

SENTINEL:GROK_LIVE_FIELD_INTENT_DECODE_DEPTH_V1

**热层极短：** `.grok/rules/36-grok-live-field-intent-decode.md`
**合同：** `grok_live_field_intent_decode.v1.json`

## 外部成熟轻量搜（展开）

| 要 | 不要 |
|----|------|
| 真外搜（短查、少量权威源） | 本地 rg 冒充外搜 |
| 只取常形 / 分层 / 验收 / 反模式 | 脑内常识冒充已核对 |
| 用来补全用户没说清的技术省略 | 写成调研长文拖死当轮 |
| 与 distill **A01** 同构 | 只背岛内旧名词不搜 |

**为何最重要：** 用户口语与技术表述常不足；外部成熟是补全省略的**主源**，不是点缀。

## 三角

1. **外部成熟（轻量真搜）** — 主补充
2. **本机现状** — 接得上吗、效果怎样
3. **口语线索** — 常不完整；字面权重最低

落点机制 = 解码之后，不得当标题。

## 做（全量）

1. **解码前必轻量外搜** — 对照口语/技术表述不足，补常形（非 rg 冒充）
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
