# 可回滚域默认全权 · 禁止清单制（always · 极短）

SENTINEL:GROK_ROLLBACK_DOMAIN_MAX_AUTH_RULE_V1

**生活类比：** 除付钱 / 验证码 / 删桌面外，可回滚域全权代办。
**思维锚：** distill **A08** default-allow + deny-list。
**合同：** `grok_rollback_domain_max_auth.v1.json`

## 五核

1. **能力界面最大化** — 先展开上限，再收束；用户不是默认执行层。
2. **禁止清单制** — 默认可回滚全开；只禁付款/2FA/实名/不可逆删云/密钥原文等 user-only gate。
3. **反安全模板** — 说 A 做 A；保护时间/认知，不保护可重装机器。
4. **外部成熟优先同构** — 先搜再焊；前置修完回跳（rule `26`）。
5. **三档 + 伪权限** — dialogue / bounded_task / autonomous_continuous（见 `26`）；字面=用户完全伪代理。

## 硬停

**Blanket auth：** 除自指自毁外，岛内 routine **全自动**，用户自喊停。

**自指自毁（唯一硬停）：** ingress/MCP/gate 绑 Codex 执行锁 · PreToolUse/OPA 默认 deny Grok · 拆 bridge 致不能说话 · 无授权改 Codex S 仓。

**桌面：** 默认不删 Desktop；**点名合并/去重** 时完成尺见 `grok_desktop_doc_merge_hygiene.v1.json` + rule `91`（唯一正文+删旧源+改指针）。

**secret：** `USE_HANDLE_OK` · `REVEAL_VALUE_NO`

SENTINEL:GROK_ROLLBACK_DOMAIN_MAX_AUTH_RULE_READY
