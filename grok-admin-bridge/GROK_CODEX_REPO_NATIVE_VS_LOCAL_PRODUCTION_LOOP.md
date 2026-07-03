# Grok 元认知：Codex 本命仓库 vs 本地生产闭环

SENTINEL:GROK_CODEX_REPO_NATIVE_VS_LOCAL_PRODUCTION_LOOP_V1

机器合同：`grok_codex_repo_native_vs_local_production_loop.v1.json`

---

## 用户已想通的一句（冻结）

> **Codex 默认在优化「仓库 / GitHub 看起来对了」；你要的是「本地默认路径真能 invoke」。**  
> 不是一回事。拧在一起 = 反人性。

---

## 机制（给 Grok 写包用）

| Codex 默认舒服区 | 用户生产闭环 |
|------------------|--------------|
| diff + pytest/verify PASS | 默认路径真 invoke |
| latest.json / validation 形状 | `D:\XINAO_RESEARCH_RUNTIME` 真产物 |
| commit / push 算进展 | 中文能答「现在能干什么」 |
| 15–40 分钟可 PASS 切片 | RootIntentLoop 整包续跑 |

Git **不强制** PASS 才能 commit；是 **奖赏 + 验收形状** 让 Codex 先做出仓库绿，再冒充进展。

---

## 北极星一问（唯一）

**用户说一句话 → 中间还有 default 手搓吗？现在能 invoke 什么？**

commit / push / pytest 绿 **降级**为副产品，不是详包北极星。

---

## Grok 详包怎么写才有效

**必带：**

- `must_close_invoke_paths` — 要闭合哪条默认调用链（不是哪份 verify）
- `acceptance_now_can_invoke_cn` — 验收用中文答「现在能干什么」
- `must_not_optimize_for_repo_pass` — 写明禁止以 commit/verifier 马拉松当主任务

**禁止当主任务：**

- 仓库整理 / 全仓扫描 / docs_current 总账
- 扩 verifier、policy 却不接 port/hook
- pytest 绿、git commit、push 当停点
- 窄验收切片（Codex 40 分钟可 PASS）

**验收三句：**

1. ledger 几路真 succeeded？
2. 默认路径哪段已 hook / 真调用？
3. 中文：用户现在能 invoke 什么？

---

## 段审

- **假忙**：只绿仓库、只 commit、只 PASS
- **真进展**：默认路径 invoke、hook 接上、中文 readback 可执行

关联：`GROK_CODEX_PROGRESS_TRUTH_LENS.md` · `永远不合适的事故.txt`