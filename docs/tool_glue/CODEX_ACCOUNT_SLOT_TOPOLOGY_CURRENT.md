# 本机 Codex 账号槽拓扑（Current）

## 不变量

本机不是四副 Codex 身体，而是两副互不交叉的身体、每副各有两个账号槽：

```text
OPEN CODEX S HARDMODE.lnk <-> CodexB.lnk
同一个 S 工程/行为运行体；仅账号附着状态隔离。

CodexA.lnk <-> CodexC.lnk
同一个 E:\CODEX_CLEANROOM 运行体和新仓库；仅账号附着状态隔离。
```

因此：

- C 绝不连接 S/B 的配置、AGENTS、Skills、Plugins、runtime 或工作树；
- B 绝不连接 A/C 的 clean-room 身体；
- A/C 共用 `E:\CODEX_CLEANROOM\Open-Codex-Cleanroom.ps1`、`workspace`、runtime、配置源、语义与能力面；
- A/C 只分别持有自己的 `auth.json`、token refresh、sessions/history、SQLite/activity state 与其他产品强制依附 `CODEX_HOME` 的账号状态；
- `A 并发研究` / `C 并发研究` 是同一 world-compute operation 加一个 `account_slot=A|C` 选择，不是两种研究协议、两种 cognition、两套 controller 或历史实验 arm；run 一旦创建，恢复必须继续使用该 run 冻结的 slot；
- 账号身份由用户指定；本次用户明确指定 C 直接使用 B 已登录的账号，因此只把 B 的 `auth.json` 作为一次性凭证种子复制到 C 的物理账户载体。它不建立回 S/B 的链接，也不复制 B 的 sessions/history/config/Skills 或工作树。

## 2026-08-12 机械观察

- 当前 CodexA 的 `account_id` 与 S 主入口相同，与 CodexB 不同；仅做等值比较，没有记录 ID 或 token；
- CodexC 初建时没有 `auth.json`；随后依当前用户明确纠正，从 CodexB 复制了唯一的凭证文件。机械等值检查确认 C 与 B 是同一账号、C 与 A 不同，且没有输出账号 ID 或 token；
- A/C 两个 Terminal profile 都进入 `E:\CODEX_CLEANROOM\workspace`，调用同一 launcher，仅 `-AccountSlot A|C` 不同；
- C 的配置、Skills、Plugins 是 A clean-room canonical 对象的直接内部投影；C 的账户状态根为 `E:\CODEX_CLEANROOM\codex-home-c`。

## 验收意义

“一样”指真实消费者形状相同：相同 workspace/runtime/model/reasoning/权限/网络/shell/工具/语义/界面和启动源码。路径中为选择账号槽而存在的 `A|C` 标签，以及账号附着状态的独立路径，是唯一允许的差异；它们不能演化成第二份配置或第二套行为。

历史 one-shot 实验若仍需引用 A/B/C/D，应按 `experiment_arm` 归档，并优先使用描述性名称（例如 `NATURAL`、`WORLD_SYNTHESIS`、`PROBE_CONTROL`、`FULL_AGENCY`）；单字母 arm 不进入长期 runtime 热语义，也不能解释用户所说的账号槽 A/C。
