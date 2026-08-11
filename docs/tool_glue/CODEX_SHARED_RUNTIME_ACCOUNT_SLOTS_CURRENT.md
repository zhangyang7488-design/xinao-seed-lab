# Codex 共享运行体与双认证槽

`SENTINEL:ONE_CODEX_RUNTIME_TWO_CREDENTIAL_SLOTS_V1`

状态：`current / installed / reversible`

## 正确身份

本机只有一个 Codex 工程与行为运行体。A、B 不是两个认识主体、两套配置、两个恢复系统或两个长期窗口制度；它们只是同一个运行体的两个 ChatGPT 认证入口，用于额度轮换：

```text
shared Codex runtime
  config / AGENTS / hooks / profiles / skills / rules / plugins
  S repository / D runtime / behavior regressions / recovery
                 |
          +------+------+
          |             |
   credential A   credential B
          |             |
      auth A          auth B
```

## 同一真实对象

以下对象只有一个 live 语义源，B 通过 NTFS link 直接消费主 Codex home 的同一对象，不做复制、双向同步、哈希追平或反向恢复：

- `config.toml`
- `AGENTS.md`
- `hooks.json`
- 所有 `*.config.toml` profile
- `agents/`、`skills/`、`rules/`、`plugins/`
- `E:\XINAO_RESEARCH_WORKSPACES\S` 工作树
- `D:\XINAO_RESEARCH_RUNTIME` 中的共享运行证据与行为回归结果

因此，从 B 修改上述任一对象，A 随后读取的是同一字节；反向亦然。B 不能成为主配置的第二权威来源，主源损坏只从具名冷恢复材料恢复。

## 必须隔离的 credential carrier

Codex 当前把登录凭据和若干活动产品状态定位在 `CODEX_HOME`，所以仍保留两个 home。以下对象不链接、不复制、不互相恢复：

- `auth.json` 与 token refresh
- `sessions/`、活动 `state_*.sqlite`/WAL 和当前进程状态
- 账户或安装实例产生的缓存、锁、浏览器/MCP OAuth 状态

这不是第二套运行语义，而是产品目前没有提供独立 credential-path 参数时的最小身份 overlay。不得为了“看起来更统一”硬链接活动 SQLite/WAL 或在共享 home 中来回替换 `auth.json`。

一个正在运行的对话线程和模型采样不能被承诺为另一个进程中的隐藏状态副本。需要跨账号长期生效的行为变化，必须落到上述共享规则、Skill、仓库、测试或轨迹证据；仅存在于某个会话转录或账户本地 Memory 的内容不算完成采用。

## 入口与实现

- canonical launcher：`E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Open-Codex-S-SharedRuntime.ps1`
- A 入口：`C:\Users\xx363\CodexLaunchers\Open-Codex-S-Hardmode.ps1`
- B 入口：`C:\Users\xx363\CodexLaunchers\Open-Codex-S-Hardmode-Account-B.ps1`
- canonical runtime source：`C:\Users\xx363\.codex`
- B credential carrier：`C:\Users\xx363\.codex-s-hardmode-account-b`

两个外层入口只能选择 credential slot；共享绑定、环境清理、模型/config 读取和启动逻辑均来自同一 canonical launcher。B 对 `node_repl` 的 `CODEX_HOME` 只用一次进程级覆盖指回 B credential carrier，不生成第二份配置。

## 验收与恢复

完成必须同时证明：

1. B 的每个共享文件/目录是指向 canonical source 的真实 link，而非相同内容副本；
2. A/B `auth.json` 是普通私有文件，且已安装账户 ID 不同；
3. A/B fresh Codex 进程读取同一 config、AGENTS、Skills 与 hooks，hook trust 均成立；
4. 在 B 改动一个可逆共享 canary，A 不经同步立即读到；回滚 canary 后两边同时恢复；
5. S 行为回归从任一 credential slot 产生的仓库/运行证据由另一入口直接可见；
6. 冷恢复只封装 canonical runtime 与薄入口，不封装认证、sessions、Memory 数据，也不把 B 当恢复源。

迁移前副本保存在具名 operation backup 中；回滚时先停止 A/B 新进程，再恢复薄入口与 B 原文件。不得从 B 的投影反推 canonical source。
